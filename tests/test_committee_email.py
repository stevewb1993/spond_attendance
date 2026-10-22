"""Tests for spond_attendance.committee_email module."""

import json
from datetime import date

import pandas as pd
import pytest

from spond_attendance import committee_email


@pytest.fixture
def data_dir(tmp_path):
    rows = [
        ("STV Swim", "2025-10-06", "Monday", 10),
        ("STV Swim", "2026-10-05", "Monday", 13),
        ("Indoor Bike", "2026-10-06", "Tuesday", 8),
        ("STV Swim", "2026-11-02", "Monday", 9),
    ]
    attendance = pd.DataFrame(
        rows,
        columns=pd.Index(
            ["session_name", "session_date", "session_day_of_week", "attended"]
        ),
    )
    attendance.to_csv(tmp_path / "session_attendance.csv", sep="|", index=False)
    pd.DataFrame(
        {"session_name": ["STV Swim", "Indoor Bike"], "category": ["Swim", "Bike"]}
    ).to_csv(tmp_path / "session_types.csv", index=False)
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    """Capture Brevo requests instead of sending them."""
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"messageId": "1"}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        return Response()

    monkeypatch.setattr(committee_email, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(committee_email.urllib.request, "urlopen", fake_urlopen)
    for var in ("EMAIL_TO", "EMAIL_FROM", "EMAIL_FROM_NAME", "EMAIL_BCC"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BREVO_API_KEY", "test-key")
    return requests


@pytest.mark.parametrize(
    ("today", "expected"),
    [(date(2026, 11, 2), (2026, 10)), (date(2027, 1, 2), (2026, 12))],
)
def test_previous_month(today, expected):
    assert committee_email.previous_month(today) == expected


def test_sends_table_ending_with_month(data_dir, sent):
    committee_email.main(["-d", str(data_dir), "--month", "2026-10", "--months", "2"])

    assert len(sent) == 1
    request = sent[0]
    assert request.full_url == committee_email.BREVO_URL
    assert request.get_header("Api-key") == "test-key"
    payload = json.loads(request.data)
    assert payload["sender"] == {
        "email": "bathamphibiansbookings@gmail.com",
        "name": "Bath Amphibians",
    }
    assert payload["to"] == [{"email": "amphibs-committee@googlegroups.com"}]
    assert payload["bcc"] == [
        {"email": "stevewbowser@gmail.com"},
        {"email": "bathamphibiansbookings@gmail.com"},
    ]
    assert payload["subject"] == "Attendance update — October 2026"
    html = payload["htmlContent"]
    assert "Sep 2026" in html and "Oct 2026" in html
    # November is after the reported month, so it is left out
    assert "Nov 2026" not in html
    assert "13.0" in payload["textContent"]


def test_to_overrides_recipient(data_dir, sent):
    committee_email.main(
        ["-d", str(data_dir), "--month", "2026-10", "--to", "me@example.com"]
    )

    assert json.loads(sent[0].data)["to"] == [{"email": "me@example.com"}]


def test_bcc_leaves_out_addresses_already_sent_to(data_dir, sent):
    committee_email.main(
        ["-d", str(data_dir), "--month", "2026-10", "--to", "StevewBowser@gmail.com"]
    )

    assert json.loads(sent[0].data)["bcc"] == [
        {"email": "bathamphibiansbookings@gmail.com"}
    ]


def test_bcc_from_environment(data_dir, sent, monkeypatch):
    monkeypatch.setenv("EMAIL_BCC", "a@example.com, b@example.com")
    committee_email.main(["-d", str(data_dir), "--month", "2026-10"])

    assert json.loads(sent[0].data)["bcc"] == [
        {"email": "a@example.com"},
        {"email": "b@example.com"},
    ]


def test_dry_run_writes_preview_without_sending(data_dir, sent, tmp_path):
    preview = tmp_path / "preview.html"
    committee_email.main(
        [
            "-d",
            str(data_dir),
            "--month",
            "2026-10",
            "--dry-run",
            "--preview",
            str(preview),
        ]
    )

    assert sent == []
    assert "<table" in preview.read_text(encoding="utf-8")


def test_refuses_month_without_data(data_dir, sent, capsys):
    with pytest.raises(SystemExit):
        committee_email.main(["-d", str(data_dir), "--month", "2026-12"])

    assert sent == []
    assert "No attendance for December 2026" in capsys.readouterr().err


def test_requires_api_key(data_dir, sent, monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY")
    with pytest.raises(SystemExit):
        committee_email.main(["-d", str(data_dir), "--month", "2026-10"])

    assert sent == []


def test_bad_month_is_rejected(data_dir, sent):
    with pytest.raises(SystemExit):
        committee_email.main(["-d", str(data_dir), "--month", "2026-13"])
