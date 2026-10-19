"""Tests for spond_attendance.fetch module."""

import json
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from spond_attendance.fetch import (
    SEARCH_LIMIT,
    SpondClient,
    SpondError,
    Tokens,
    authenticate,
    export_filename,
    find_events,
    load_tokens,
    main,
    month_chunks,
    save_tokens,
    start_of_month_before,
)

GROUP = "GROUP1"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
XLSX = b"PK\x03\x04fake workbook"


def body_of(request: urllib.request.Request):
    assert isinstance(request.data, bytes)
    return json.loads(request.data)


def token_response(access="access-1", refresh="refresh-1"):
    return {
        "accessToken": {"token": access, "expiration": "2026-10-20T12:00:00Z"},
        "refreshToken": {"token": refresh, "expiration": "2027-01-17T12:00:00Z"},
    }


def spond(spond_id, start, name="STV Swim"):
    return {"spondId": spond_id, "name": name, "startTimestamp": start}


class FakeSpond:
    """Records requests and answers them from canned responses."""

    def __init__(self, events=(), login=None, two_factor=None, refresh=None):
        self.events = list(events)
        self.login_response = login or token_response()
        self.two_factor_response = two_factor
        self.refresh_response = refresh
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request) -> bytes:
        self.requests.append(request)
        url = urllib.parse.urlparse(request.full_url)
        path = url.path.removeprefix("/core/v1/")
        body = body_of(request) if request.data else None

        if path == "auth2/login":
            return json.dumps(self.login_response).encode()
        if path == "auth2/2fa/verify":
            assert body is not None
            return json.dumps(self.two_factor_response).encode()
        if path == "auth2/login/refresh":
            if self.refresh_response is None:
                raise SpondError("HTTP 401")
            return json.dumps(self.refresh_response).encode()
        if path == f"search/groups/{GROUP}/sponds":
            query = dict(urllib.parse.parse_qsl(url.query))
            start, end = query["fromTimestamp"], query["toTimestamp"]
            hits = [e for e in self.events if start <= e["startTimestamp"][:10] <= end]
            return json.dumps(hits).encode()
        if path == f"group/{GROUP}/exportAttendance":
            return XLSX
        raise AssertionError(f"Unexpected request {request.full_url}")

    def paths(self):
        return [urllib.parse.urlparse(r.full_url).path for r in self.requests]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


class TestMonthChunks:
    def test_splits_on_month_boundaries(self):
        assert month_chunks(date(2026, 4, 8), date(2026, 6, 3)) == [
            (date(2026, 4, 8), date(2026, 4, 30)),
            (date(2026, 5, 1), date(2026, 5, 31)),
            (date(2026, 6, 1), date(2026, 6, 3)),
        ]

    def test_single_day(self):
        day = date(2026, 10, 7)
        assert month_chunks(day, day) == [(day, day)]

    def test_crosses_year_end(self):
        chunks = month_chunks(date(2025, 12, 15), date(2026, 1, 10))
        assert chunks == [
            (date(2025, 12, 15), date(2025, 12, 31)),
            (date(2026, 1, 1), date(2026, 1, 10)),
        ]


class TestStartOfMonthBefore:
    def test_three_months(self):
        assert start_of_month_before(date(2026, 10, 19), 3) == date(2026, 7, 1)

    def test_across_year(self):
        assert start_of_month_before(date(2026, 2, 15), 3) == date(2025, 11, 1)

    def test_zero_is_this_month(self):
        assert start_of_month_before(date(2026, 8, 31), 0) == date(2026, 8, 1)


def test_export_filename_matches_pipeline_pattern():
    assert export_filename(date(2026, 10, 19)) == "spond_attendance_2026-10.xlsx"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TestClient:
    def test_requests_carry_bearer_token(self):
        fake = FakeSpond()
        client = SpondClient("tok", transport=fake)
        client.search_past_events(GROUP, date(2026, 10, 1), date(2026, 10, 31))
        assert fake.requests[0].get_header("Authorization") == "Bearer tok"

    def test_search_hitting_limit_raises(self):
        events = [spond(f"S{i}", "2026-10-01T18:00:00Z") for i in range(SEARCH_LIMIT)]
        client = SpondClient("tok", transport=FakeSpond(events))
        with pytest.raises(SpondError, match="search limit"):
            client.search_past_events(GROUP, date(2026, 10, 1), date(2026, 10, 1))

    def test_export_posts_spond_ids(self):
        fake = FakeSpond()
        client = SpondClient("tok", transport=fake)
        assert client.export_attendance(GROUP, ["A", "B"]) == XLSX
        assert body_of(fake.requests[0]) == {"spondIds": ["A", "B"]}

    def test_export_rejects_non_xlsx(self):
        client = SpondClient("tok", transport=lambda request: b'{"error": "x"}')
        with pytest.raises(SpondError, match="not an .xlsx"):
            client.export_attendance(GROUP, ["A"])

    def test_unauthenticated_request_refused(self):
        client = SpondClient(transport=FakeSpond())
        with pytest.raises(SpondError, match="Not signed in"):
            client.export_attendance(GROUP, ["A"])

    def test_login_with_two_factor(self):
        fake = FakeSpond(
            login={"token": "2fa-token", "phoneNumber": "+447700900000"},
            two_factor=token_response(access="after-2fa"),
        )
        client = SpondClient(transport=fake)
        tokens = client.login("a@b.c", "pw", prompt_2fa_code=lambda phone: "123456")
        assert tokens.access_token == "after-2fa"
        assert client.access_token == "after-2fa"
        assert body_of(fake.requests[1]) == {
            "token": "2fa-token",
            "code": "123456",
            "phoneNumber": "+447700900000",
        }


class TestFindEvents:
    def test_searches_month_by_month_and_sorts(self):
        fake = FakeSpond(
            [
                spond("B", "2026-05-02T07:00:00Z"),
                spond("A", "2026-04-08T17:45:00Z"),
                spond("OUT", "2026-03-30T17:45:00Z"),
            ]
        )
        client = SpondClient("tok", transport=fake)
        events = find_events(client, GROUP, date(2026, 4, 8), date(2026, 5, 31))
        assert [e.spond_id for e in events] == ["A", "B"]
        assert len(fake.requests) == 2


# ---------------------------------------------------------------------------
# Authentication and token cache
# ---------------------------------------------------------------------------


class TestTokenCache:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "nested" / "tokens.json"
        tokens = Tokens.from_response(token_response())
        save_tokens(path, tokens)
        assert load_tokens(path) == tokens

    def test_missing_or_corrupt_file(self, tmp_path):
        assert load_tokens(tmp_path / "none.json") is None
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        assert load_tokens(bad) is None


class TestAuthenticate:
    def test_env_token_wins(self, tmp_path):
        fake = FakeSpond()
        client = SpondClient(transport=fake)
        authenticate(client, tmp_path / "t.json", NOW, {"SPOND_TOKEN": "env-tok"})
        assert client.access_token == "env-tok"
        assert fake.requests == []

    def test_uses_unexpired_cached_token(self, tmp_path):
        path = tmp_path / "t.json"
        save_tokens(path, Tokens("cached", NOW + timedelta(hours=1), "r", None))
        fake = FakeSpond()
        client = SpondClient(transport=fake)
        authenticate(client, path, NOW, {})
        assert client.access_token == "cached"
        assert fake.requests == []

    def test_refreshes_expired_token(self, tmp_path):
        path = tmp_path / "t.json"
        save_tokens(path, Tokens("old", NOW - timedelta(hours=1), "refresh-old"))
        fake = FakeSpond(refresh=token_response(access="new", refresh="refresh-new"))
        client = SpondClient(transport=fake)
        authenticate(client, path, NOW, {})
        assert client.access_token == "new"
        assert body_of(fake.requests[0]) == {"value": "refresh-old"}
        cached = load_tokens(path)
        assert cached is not None and cached.refresh_token == "refresh-new"

    def test_logs_in_when_refresh_fails(self, tmp_path):
        path = tmp_path / "t.json"
        save_tokens(path, Tokens("old", NOW - timedelta(hours=1), "refresh-old"))
        fake = FakeSpond(login=token_response(access="fresh"))
        client = SpondClient(transport=fake)
        env = {"SPOND_USERNAME": "a@b.c", "SPOND_PASSWORD": "pw"}
        authenticate(client, path, NOW, env)
        assert client.access_token == "fresh"
        assert body_of(fake.requests[-1]) == {
            "email": "a@b.c",
            "password": "pw",
        }

    def test_no_credentials_without_terminal(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        client = SpondClient(transport=FakeSpond())
        with pytest.raises(SpondError, match="SPOND_USERNAME"):
            authenticate(client, tmp_path / "t.json", NOW, {})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_api(monkeypatch):
    fake = FakeSpond([spond("A", "2026-10-07T17:45:00Z")])
    monkeypatch.setattr("spond_attendance.fetch.urllib_transport", fake)
    # Keep a developer's real .env out of the tests.
    monkeypatch.setattr("spond_attendance.fetch.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("SPOND_TOKEN", "env-tok")
    return fake


def run(tmp_path: Path, *extra: str):
    main(
        [
            str(tmp_path),
            "--group-id",
            GROUP,
            "--since",
            "2026-10-01",
            "--until",
            "2026-10-19",
            "--token-file",
            str(tmp_path / "tokens.json"),
            *extra,
        ]
    )


class TestMain:
    def test_saves_export(self, tmp_path, fake_api):
        run(tmp_path)
        assert (tmp_path / "spond_attendance_2026-10.xlsx").read_bytes() == XLSX

    def test_refuses_to_overwrite(self, tmp_path, fake_api, capsys):
        (tmp_path / "spond_attendance_2026-10.xlsx").write_bytes(b"old")
        with pytest.raises(SystemExit):
            run(tmp_path)
        assert "--force" in capsys.readouterr().err
        assert (tmp_path / "spond_attendance_2026-10.xlsx").read_bytes() == b"old"

    def test_force_overwrites(self, tmp_path, fake_api):
        (tmp_path / "spond_attendance_2026-10.xlsx").write_bytes(b"old")
        run(tmp_path, "--force")
        assert (tmp_path / "spond_attendance_2026-10.xlsx").read_bytes() == XLSX

    def test_default_window_is_three_months_back(self, tmp_path, fake_api):
        main([str(tmp_path), "--group-id", GROUP, "--until", "2026-10-19"])
        first = urllib.parse.urlparse(fake_api.requests[0].full_url)
        query = dict(urllib.parse.parse_qsl(first.query))
        assert query["fromTimestamp"] == "2026-07-01"
        assert sum("search" in p for p in fake_api.paths()) == 4

    def test_dry_run_lists_events_only(self, tmp_path, fake_api, capsys):
        run(tmp_path, "--dry-run")
        assert "2026-10-07 17:45 UTC  STV Swim" in capsys.readouterr().out
        assert not (tmp_path / "spond_attendance_2026-10.xlsx").exists()
        assert not any("exportAttendance" in p for p in fake_api.paths())
