"""Email the monthly year-over-year attendance table to the committee.

The table is the dashboard's YoY Summary with its default sessions, the same
one its "Copy table for email" button copies. It is sent through Brevo's HTTPS
API, from the sender address verified there (as spond-cancellation does).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from .summary import (
    DEFAULT_MONTHS,
    DEFAULT_SESSIONS,
    YoySummary,
    html_table,
    load_attendance,
    yoy_summary,
)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_FROM = "bathamphibiansbookings@gmail.com"
DEFAULT_FROM_NAME = "Bath Amphibians"
DEFAULT_TO = "amphibs-committee@googlegroups.com"


class EmailError(Exception):
    """The report could not be built or sent."""


def previous_month(today: date) -> tuple[int, int]:
    """The last complete month before today."""
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def parse_month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}") from None
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}")
    return year, month


def month_name(month: tuple[int, int]) -> str:
    return date(month[0], month[1], 1).strftime("%B %Y")


def build_report(
    data_dir: Path, month: tuple[int, int], num_months: int = DEFAULT_MONTHS
) -> YoySummary:
    """The summary for the default sessions over num_months months ending month."""
    df = load_attendance(data_dir)
    sessions = [s for names in DEFAULT_SESSIONS.values() for s in names]
    in_month = df[
        df["session_name"].isin(sessions)
        & (df["year"] == month[0])
        & (df["month"] == month[1])
    ]
    # A table ending in an empty month means the data was not refreshed.
    if in_month.empty:
        raise EmailError(
            f"No attendance for {month_name(month)} in {data_dir}. "
            f"Run spond-update first."
        )
    summary = yoy_summary(df, df, sessions, num_months, end=month)
    if summary is None:
        raise EmailError(f"No attendance to report for {month_name(month)}.")
    return summary


def subject(month: tuple[int, int]) -> str:
    return f"Attendance update — {month_name(month)}"


def html_body(summary: YoySummary, month: tuple[int, int]) -> str:
    intro = (
        f"Hi all,<br><br>Here are the attendance numbers up to the end of "
        f"{month_name(month)}. Each figure is the average attendance per session "
        f"that month, and the bracketed number is the change from the same month "
        f"last year."
    )
    footer = "Sent automatically from the Spond attendance data."
    return (
        f'<div style="font-family:Arial,sans-serif;font-size:14px">'
        f"<p>{intro}</p>{html_table(summary)}"
        f'<p style="color:#757575;font-size:12px">{footer}</p></div>'
    )


def text_body(summary: YoySummary, month: tuple[int, int]) -> str:
    return (
        f"Attendance numbers up to the end of {month_name(month)}: average "
        f"attendance per session, with the change from the same month last year "
        f"in brackets.\n\n{summary.to_frame().to_string()}\n"
    )


def send_email(
    api_key: str,
    sender: str,
    sender_name: str,
    to: list[str],
    subject: str,
    html: str,
    text: str,
) -> None:
    """Send one email through Brevo. Raises EmailError on failure."""
    payload = {
        "sender": {"email": sender, "name": sender_name},
        "to": [{"email": address} for address in to],
        "replyTo": {"email": sender},
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    request = urllib.request.Request(
        BREVO_URL,
        data=json.dumps(payload).encode(),
        headers={
            "api-key": api_key,
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise EmailError(f"Brevo rejected the email ({e.code}): {detail}") from e
    except urllib.error.URLError as e:
        raise EmailError(f"Could not reach Brevo: {e.reason}") from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="spond-email",
        description=(
            "Email the dashboard's year-over-year attendance table to the committee."
        ),
    )
    parser.add_argument(
        "-d",
        "--data-dir",
        type=Path,
        default=Path("output_data"),
        help="Directory with session_attendance.csv (default: output_data/)",
    )
    parser.add_argument(
        "--month",
        type=parse_month,
        default=None,
        help="Last month in the table, YYYY-MM (default: last month)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=DEFAULT_MONTHS,
        help=f"Months the table covers (default: {DEFAULT_MONTHS})",
    )
    parser.add_argument(
        "--to",
        action="append",
        help=f"Recipient, repeatable (default: EMAIL_TO or {DEFAULT_TO})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the email to --preview instead of sending it",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=Path("email_preview.html"),
        help="Where --dry-run writes the email (default: email_preview.html)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    load_dotenv(find_dotenv(usecwd=True))
    args = parse_args(argv)
    month = args.month or previous_month(date.today())
    to = args.to or [os.environ.get("EMAIL_TO") or DEFAULT_TO]

    try:
        summary = build_report(args.data_dir, month, args.months)
    except EmailError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    html = html_body(summary, month)

    if args.dry_run:
        args.preview.write_text(html, encoding="utf-8")
        print(f"Would send {subject(month)!r} to {', '.join(to)}.")
        print(f"Preview written to {args.preview}")
        return

    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        print("Error: BREVO_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    try:
        send_email(
            api_key,
            os.environ.get("EMAIL_FROM") or DEFAULT_FROM,
            os.environ.get("EMAIL_FROM_NAME") or DEFAULT_FROM_NAME,
            to,
            subject(month),
            html,
            text_body(summary, month),
        )
    except EmailError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Sent {subject(month)!r} to {', '.join(to)}.")
