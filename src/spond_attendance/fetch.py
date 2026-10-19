"""Download attendance exports from the Spond API.

The Spond web client's "Export attendance history" dialog does two things,
which this module repeats:

1. ``GET /search/groups/{group}/sponds`` lists past events (sponds) between
   two dates. The search returns at most 500 events, newest first, so a long
   window is searched one month at a time.
2. ``POST /group/{group}/exportAttendance`` with ``{"spondIds": [...]}``
   returns the attendance workbook for those events — the same .xlsx file the
   dialog downloads.

Authentication uses the bearer token from ``POST /auth2/login``. Tokens are
cached so later runs refresh them instead of asking for the password again.
"""

from __future__ import annotations

import argparse
import calendar
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

API_URL = "https://api.spond.com/core/v1"
API_LEVEL = "2.7.14"

# Bath Amphibians
DEFAULT_GROUP_ID = "7C12D9BF8CA644BAA90CCB6F8FA0C355"

DEFAULT_MONTHS = 3

# The search endpoint stops at this many results.
SEARCH_LIMIT = 500

# Refresh an access token this long before it expires.
TOKEN_EXPIRY_MARGIN = timedelta(minutes=5)

XLSX_MAGIC = b"PK"


class SpondError(RuntimeError):
    """A Spond API request failed."""


@dataclass(frozen=True)
class Event:
    spond_id: str
    name: str
    start: datetime


@dataclass(frozen=True)
class Tokens:
    access_token: str
    access_expiration: datetime | None = None
    refresh_token: str | None = None
    refresh_expiration: datetime | None = None

    @classmethod
    def from_response(cls, data: dict) -> Tokens:
        access = data["accessToken"]
        refresh = data.get("refreshToken") or {}
        return cls(
            access_token=access["token"],
            access_expiration=_parse_timestamp(access.get("expiration")),
            refresh_token=refresh.get("token"),
            refresh_expiration=_parse_timestamp(refresh.get("expiration")),
        )

    @classmethod
    def from_json(cls, data: dict) -> Tokens:
        return cls(
            access_token=data["access_token"],
            access_expiration=_parse_timestamp(data.get("access_expiration")),
            refresh_token=data.get("refresh_token"),
            refresh_expiration=_parse_timestamp(data.get("refresh_expiration")),
        )

    def to_json(self) -> dict:
        return {
            "access_token": self.access_token,
            "access_expiration": _format_timestamp(self.access_expiration),
            "refresh_token": self.refresh_token,
            "refresh_expiration": _format_timestamp(self.refresh_expiration),
        }

    def access_valid(self, now: datetime) -> bool:
        return (
            self.access_expiration is None
            or self.access_expiration - TOKEN_EXPIRY_MARGIN > now
        )

    def refresh_valid(self, now: datetime) -> bool:
        return self.refresh_token is not None and (
            self.refresh_expiration is None or self.refresh_expiration > now
        )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def default_token_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "spond-attendance" / "tokens.json"


def load_tokens(path: Path) -> Tokens | None:
    try:
        return Tokens.from_json(json.loads(path.read_text()))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def save_tokens(path: Path, tokens: Tokens) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with owner-only permissions; the refresh token is a credential.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(tokens.to_json(), indent=2) + "\n")


# A transport sends a request and returns the response body.
Transport = Callable[[urllib.request.Request], bytes]


def urllib_transport(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise SpondError(
            f"{request.get_method()} {request.full_url} failed: "
            f"HTTP {e.code} {body}".strip()
        ) from e
    except urllib.error.URLError as e:
        raise SpondError(f"Could not reach {request.full_url}: {e.reason}") from e


class SpondClient:
    def __init__(
        self,
        access_token: str | None = None,
        transport: Transport | None = None,
        api_url: str = API_URL,
    ) -> None:
        self.access_token = access_token
        self.transport = transport or urllib_transport
        self.api_url = api_url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict | None = None,
        authenticated: bool = True,
    ) -> bytes:
        url = f"{self.api_url}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json", "Api-Level": API_LEVEL}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if authenticated:
            if not self.access_token:
                raise SpondError("Not signed in to Spond")
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        return self.transport(request)

    def _request_json(self, method: str, path: str, **kwargs):
        return json.loads(self._request(method, path, **kwargs))

    def login(
        self,
        email: str,
        password: str,
        prompt_2fa_code: Callable[[str], str] | None = None,
    ) -> Tokens:
        data = self._request_json(
            "POST",
            "auth2/login",
            body={"email": email, "password": password},
            authenticated=False,
        )
        if "accessToken" not in data and data.get("token"):
            # Two-factor authentication: Spond has texted a code.
            if prompt_2fa_code is None:
                raise SpondError(
                    "Spond asked for a two-factor code, but there is no terminal "
                    "to enter it in"
                )
            phone = data.get("phoneNumber", "")
            code = prompt_2fa_code(phone)
            data = self._request_json(
                "POST",
                "auth2/2fa/verify",
                body={"token": data["token"], "code": code, "phoneNumber": phone},
                authenticated=False,
            )
        if "accessToken" not in data:
            raise SpondError(f"Unexpected login response: {sorted(data)}")
        tokens = Tokens.from_response(data)
        self.access_token = tokens.access_token
        return tokens

    def refresh(self, refresh_token: str) -> Tokens:
        data = self._request_json(
            "POST",
            "auth2/login/refresh",
            body={"value": refresh_token},
            authenticated=False,
        )
        tokens = Tokens.from_response(data)
        self.access_token = tokens.access_token
        return tokens

    def search_past_events(self, group_id: str, start: date, end: date) -> list[Event]:
        """Past events in the group from start to end, both inclusive."""
        data = self._request_json(
            "GET",
            f"search/groups/{group_id}/sponds",
            params={
                "expired": "true",
                "fromTimestamp": start.isoformat(),
                "toTimestamp": end.isoformat(),
            },
        )
        if len(data) >= SEARCH_LIMIT:
            raise SpondError(
                f"Spond returned {len(data)} events for {start} to {end}, its "
                f"search limit, so some may be missing"
            )
        return [
            Event(
                spond_id=item["spondId"],
                name=item.get("name", ""),
                start=datetime.fromisoformat(
                    item["startTimestamp"].replace("Z", "+00:00")
                ),
            )
            for item in data
        ]

    def export_attendance(self, group_id: str, spond_ids: list[str]) -> bytes:
        content = self._request(
            "POST",
            f"group/{group_id}/exportAttendance",
            body={"spondIds": spond_ids},
        )
        if not content.startswith(XLSX_MAGIC):
            raise SpondError("Spond's attendance export was not an .xlsx file")
        return content


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split start..end (inclusive) into calendar-month pieces."""
    chunks = []
    current = start
    while current <= end:
        last_day = calendar.monthrange(current.year, current.month)[1]
        chunk_end = min(end, current.replace(day=last_day))
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def start_of_month_before(day: date, months: int) -> date:
    """The 1st of the month `months` before day's month."""
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(year, month + 1, 1)


def find_events(
    client: SpondClient, group_id: str, start: date, end: date
) -> list[Event]:
    """All past events from start to end, oldest first, without duplicates."""
    events: dict[str, Event] = {}
    for chunk_start, chunk_end in month_chunks(start, end):
        for event in client.search_past_events(group_id, chunk_start, chunk_end):
            events[event.spond_id] = event
    return sorted(events.values(), key=lambda e: e.start)


def export_filename(day: date) -> str:
    return f"spond_attendance_{day:%Y-%m}.xlsx"


def authenticate(
    client: SpondClient,
    token_path: Path,
    now: datetime,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Sign the client in, reusing cached tokens where possible.

    In order of preference: an access token in SPOND_TOKEN, a cached access
    token, a cached refresh token, then email and password (SPOND_USERNAME and
    SPOND_PASSWORD, prompting for anything missing).
    """
    env: Mapping[str, str] = os.environ if environ is None else environ

    if env.get("SPOND_TOKEN"):
        client.access_token = env["SPOND_TOKEN"]
        return

    cached = load_tokens(token_path)
    if cached and cached.access_valid(now):
        client.access_token = cached.access_token
        return
    if cached and cached.refresh_token and cached.refresh_valid(now):
        try:
            save_tokens(token_path, client.refresh(cached.refresh_token))
            return
        except SpondError as e:
            print(f"Could not refresh the saved Spond sign-in ({e})", file=sys.stderr)

    interactive = sys.stdin.isatty()
    email = env.get("SPOND_USERNAME")
    password = env.get("SPOND_PASSWORD")
    if not (email and password) and not interactive:
        raise SpondError(
            "No saved Spond sign-in. Set SPOND_USERNAME and SPOND_PASSWORD, or run "
            "interactively to be prompted."
        )
    if not email:
        email = input("Spond email: ").strip()
    if not password:
        password = getpass.getpass("Spond password: ")

    def prompt_code(phone: str) -> str:
        return input(f"Code texted to {phone or 'your phone'}: ").strip()

    tokens = client.login(email, password, prompt_code if interactive else None)
    save_tokens(token_path, tokens)


def write_atomically(path: Path, content: bytes) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(content)
    tmp.replace(path)


def download_export(
    output_path: Path,
    group_id: str,
    since: date,
    until: date,
    token_file: Path | None = None,
    dry_run: bool = False,
) -> bool:
    """Save the attendance export for past events from since to until.

    Returns whether a file was written: nothing is written when there are no
    events, or on a dry run, which lists the events instead. Raises SpondError
    if signing in or a request fails.
    """
    client = SpondClient()
    authenticate(client, token_file or default_token_path(), datetime.now(UTC))
    events = find_events(client, group_id, since, until)
    if not events:
        print(f"No past events found from {since} to {until}.")
        return False
    print(
        f"Found {len(events)} events from {events[0].start:%Y-%m-%d} "
        f"to {events[-1].start:%Y-%m-%d}."
    )
    if dry_run:
        for event in events:
            print(f"  {event.start:%Y-%m-%d %H:%M} UTC  {event.name}")
        return False
    content = client.export_attendance(group_id, [e.spond_id for e in events])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(output_path, content)
    print(f"Saved {output_path} ({len(content) // 1024} KB)")
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="spond-fetch",
        description=(
            "Download a Spond attendance export for recent events into "
            "spond_attendance_YYYY-MM.xlsx."
        ),
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=Path("data"),
        help="Directory to save the export in (default: data/)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=DEFAULT_MONTHS,
        help=f"Include this many whole months before --until's month "
        f"(default: {DEFAULT_MONTHS}). Ignored when --since is given.",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="First event date, YYYY-MM-DD (overrides --months)",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        help="Last event date, YYYY-MM-DD (default: today). Also names the file.",
    )
    parser.add_argument(
        "--group-id",
        default=os.environ.get("SPOND_GROUP_ID", DEFAULT_GROUP_ID),
        help="Spond group ID (default: Bath Amphibians)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite this month's export if it already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the events that would be exported without downloading",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help=f"Where to cache Spond sign-in tokens (default: {default_token_path()})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    # Search upwards from the working directory, so the repo's .env is found
    # from worktrees too. Variables already set take precedence.
    load_dotenv(find_dotenv(usecwd=True))
    args = parse_args(argv)
    until = args.until or date.today()
    since = args.since or start_of_month_before(until, args.months)
    if since > until:
        print(f"Error: --since {since} is after --until {until}", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir.resolve()
    output_path = output_dir / export_filename(until)
    if output_path.exists() and not (args.force or args.dry_run):
        print(
            f"Error: {output_path} already exists. Use --force to replace it, then "
            f"run spond-attendance with --full-refresh so the replaced file is "
            f"reprocessed.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        download_export(
            output_path,
            args.group_id,
            since,
            until,
            token_file=args.token_file,
            dry_run=args.dry_run,
        )
    except SpondError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
