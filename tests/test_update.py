"""Tests for spond_attendance.update module."""

from datetime import date

import pytest

from spond_attendance import update
from spond_attendance.fetch import SpondError, export_filename


@pytest.fixture
def calls(monkeypatch):
    """Stub the download and the pipeline, recording how they are called."""
    recorded = {"download": [], "pipeline": []}

    def fake_download(path, group_id, since, until):
        recorded["download"].append((path, since, until))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PK new")
        return True

    monkeypatch.setattr(update, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(update, "download_export", fake_download)
    monkeypatch.setattr(update.cli, "main", recorded["pipeline"].append)
    return recorded


def run(tmp_path, *extra):
    update.main(
        [
            "--data-dir",
            str(tmp_path / "data"),
            "-o",
            str(tmp_path / "out"),
            *extra,
        ]
    )


def test_downloads_this_month_then_runs_pipeline(tmp_path, calls):
    run(tmp_path)
    today = date.today()
    [(path, since, until)] = calls["download"]
    assert path == (tmp_path / "data" / export_filename(today)).resolve()
    assert until == today
    assert since == update.start_of_month_before(today, update.DEFAULT_MONTHS)
    assert calls["pipeline"] == [
        [str((tmp_path / "data").resolve()), "-o", str(tmp_path / "out")]
    ]


def test_replaced_export_triggers_full_refresh(tmp_path, calls):
    existing = tmp_path / "data" / export_filename(date.today())
    existing.parent.mkdir()
    existing.write_bytes(b"PK old")
    run(tmp_path, "--no-llm")
    [pipeline_args] = calls["pipeline"]
    assert "--full-refresh" in pipeline_args
    assert "--no-llm" in pipeline_args


def test_yes_is_passed_to_the_pipeline(tmp_path, calls):
    run(tmp_path, "--yes")
    [pipeline_args] = calls["pipeline"]
    assert "--yes" in pipeline_args


def test_months_option(tmp_path, calls):
    run(tmp_path, "--months", "1")
    [(_, since, _)] = calls["download"]
    assert since == update.start_of_month_before(date.today(), 1)


def test_no_events_skips_pipeline(tmp_path, calls, monkeypatch):
    monkeypatch.setattr(update, "download_export", lambda *a: False)
    run(tmp_path)
    assert calls["pipeline"] == []


def test_spond_error_exits_without_processing(tmp_path, calls, monkeypatch, capsys):
    def fail(*a):
        raise SpondError("HTTP 401")

    monkeypatch.setattr(update, "download_export", fail)
    with pytest.raises(SystemExit):
        run(tmp_path)
    assert "HTTP 401" in capsys.readouterr().err
    assert calls["pipeline"] == []
