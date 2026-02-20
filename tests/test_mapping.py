"""Tests for spond_attendance.mapping module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from spond_attendance.mapping import (
    SKIP_SENTINEL,
    _parse_json_response,
    apply_name_mappings,
    find_unmapped_names,
    load_canonical_names,
    load_name_mappings,
    load_session_types,
    prompt_user_approval,
    save_name_mappings,
    save_session_types,
    suggest_categories,
    suggest_mappings,
)


# ---------------------------------------------------------------------------
# load_name_mappings / save_name_mappings
# ---------------------------------------------------------------------------


class TestNameMappingsIO:
    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "mappings.csv"
        mappings = {"STV Swim!": "STV Swim", "Club Run*": "Club Run"}
        save_name_mappings(path, mappings)
        loaded = load_name_mappings(path)
        assert loaded == mappings

    def test_load_returns_empty_when_no_file(self, tmp_path: Path):
        assert load_name_mappings(tmp_path / "nonexistent.csv") == {}

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "a" / "b" / "mappings.csv"
        save_name_mappings(path, {"foo": "bar"})
        assert path.exists()
        assert load_name_mappings(path) == {"foo": "bar"}

    def test_save_sorted_by_raw_name(self, tmp_path: Path):
        path = tmp_path / "mappings.csv"
        mappings = {"Zebra": "Z", "Alpha": "A", "Middle": "M"}
        save_name_mappings(path, mappings)
        lines = path.read_text().strip().splitlines()
        # Header + 3 data rows, sorted alphabetically
        assert len(lines) == 4
        assert lines[1].startswith("Alpha,")
        assert lines[2].startswith("Middle,")
        assert lines[3].startswith("Zebra,")


# ---------------------------------------------------------------------------
# load_canonical_names
# ---------------------------------------------------------------------------


class TestLoadCanonicalNames:
    def test_loads_names_from_csv(self, tmp_path: Path):
        path = tmp_path / "session_types.csv"
        path.write_text("session_name,category\nSTV Swim,Swim\nIndoor Bike,Bike\n")
        names = load_canonical_names(path)
        assert names == {"STV Swim", "Indoor Bike"}

    def test_returns_empty_when_no_file(self, tmp_path: Path):
        assert load_canonical_names(tmp_path / "nonexistent.csv") == set()


# ---------------------------------------------------------------------------
# load_session_types / save_session_types
# ---------------------------------------------------------------------------


class TestSessionTypesIO:
    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "types.csv"
        types = {"STV Swim": "Swim", "Indoor Bike": "Bike"}
        save_session_types(path, types)
        loaded = load_session_types(path)
        assert loaded == types

    def test_load_returns_empty_when_no_file(self, tmp_path: Path):
        assert load_session_types(tmp_path / "nonexistent.csv") == {}

    def test_save_sorted_by_name(self, tmp_path: Path):
        path = tmp_path / "types.csv"
        types = {"Zebra": "Other", "Alpha": "Swim"}
        save_session_types(path, types)
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 3
        assert lines[1].startswith("Alpha,")
        assert lines[2].startswith("Zebra,")


# ---------------------------------------------------------------------------
# find_unmapped_names
# ---------------------------------------------------------------------------


class TestFindUnmappedNames:
    def test_all_canonical_returns_empty(self):
        session_names = {"STV Swim", "Indoor Bike"}
        mappings: dict[str, str] = {}
        canonical = {"STV Swim", "Indoor Bike"}
        assert find_unmapped_names(session_names, mappings, canonical) == set()

    def test_mapped_names_excluded(self):
        session_names = {"STV Swim!", "Indoor Bike"}
        mappings = {"STV Swim!": "STV Swim"}
        canonical = {"STV Swim", "Indoor Bike"}
        assert find_unmapped_names(session_names, mappings, canonical) == set()

    def test_unmapped_names_returned(self):
        session_names = {"STV Swim!", "New Session", "Indoor Bike"}
        mappings: dict[str, str] = {}
        canonical = {"Indoor Bike"}
        assert find_unmapped_names(session_names, mappings, canonical) == {
            "STV Swim!",
            "New Session",
        }

    def test_empty_inputs(self):
        assert find_unmapped_names(set(), {}, set()) == set()


# ---------------------------------------------------------------------------
# apply_name_mappings
# ---------------------------------------------------------------------------


class TestApplyNameMappings:
    def test_replaces_mapped_names(self):
        df = pd.DataFrame(
            {
                "name": ["Alice", "Bob"],
                "session_name": ["STV Swim!", "Indoor Bike"],
                "attended": [1, 1],
            }
        )
        mappings = {"STV Swim!": "STV Swim"}
        result = apply_name_mappings(df, mappings)
        assert list(result["session_name"]) == ["STV Swim", "Indoor Bike"]

    def test_leaves_unmapped_names_unchanged(self):
        df = pd.DataFrame({"session_name": ["Already Canonical"]})
        result = apply_name_mappings(df, {"Other": "Mapped"})
        assert list(result["session_name"]) == ["Already Canonical"]

    def test_empty_mappings_returns_unchanged(self):
        df = pd.DataFrame({"session_name": ["A", "B"]})
        result = apply_name_mappings(df, {})
        assert list(result["session_name"]) == ["A", "B"]

    def test_does_not_modify_original(self):
        df = pd.DataFrame({"session_name": ["STV Swim!"]})
        apply_name_mappings(df, {"STV Swim!": "STV Swim"})
        assert df["session_name"].iloc[0] == "STV Swim!"

    def test_skip_sentinel_ignored(self):
        df = pd.DataFrame({"session_name": ["Skipped Name", "STV Swim!"]})
        mappings = {"Skipped Name": SKIP_SENTINEL, "STV Swim!": "STV Swim"}
        result = apply_name_mappings(df, mappings)
        assert list(result["session_name"]) == ["Skipped Name", "STV Swim"]


# ---------------------------------------------------------------------------
# suggest_mappings (mocked CLI)
# ---------------------------------------------------------------------------


class TestSuggestMappings:
    @patch("subprocess.run")
    def test_calls_claude_cli_and_parses_response(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"STV Swim!": "STV Swim", "New Thing": "New Thing"}',
            stderr="",
        )

        result = suggest_mappings(
            unmapped={"STV Swim!", "New Thing"},
            known_canonical={"STV Swim", "Indoor Bike"},
        )

        assert result == {"STV Swim!": "STV Swim", "New Thing": "New Thing"}
        mock_run.assert_called_once()

        call_args = mock_run.call_args
        cmd = call_args.args[0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        # The prompt should mention the canonical names
        prompt_text = cmd[cmd.index("-p") + 1]
        assert "STV Swim" in prompt_text
        assert "Indoor Bike" in prompt_text

    @patch("subprocess.run")
    def test_raises_on_cli_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="some error",
        )

        with pytest.raises(RuntimeError, match="Claude CLI failed"):
            suggest_mappings(unmapped={"Foo"}, known_canonical=set())


# ---------------------------------------------------------------------------
# suggest_categories (mocked CLI)
# ---------------------------------------------------------------------------


class TestSuggestCategories:
    @patch("subprocess.run")
    def test_calls_claude_cli_and_parses_response(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"Green event": "Other", "New Swim": "Swim"}',
            stderr="",
        )

        result = suggest_categories(
            uncategorized={"Green event", "New Swim"},
            existing_types={"STV Swim": "Swim", "Indoor Bike": "Bike"},
        )

        assert result == {"Green event": "Other", "New Swim": "Swim"}
        mock_run.assert_called_once()

        call_args = mock_run.call_args
        cmd = call_args.args[0]
        assert cmd[0] == "claude"
        prompt_text = cmd[cmd.index("-p") + 1]
        assert "Swim" in prompt_text
        assert "Bike" in prompt_text


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_plain_json(self):
        assert _parse_json_response('{"a": "b"}') == {"a": "b"}

    def test_json_in_markdown_fence(self):
        text = '```json\n{"a": "b"}\n```'
        assert _parse_json_response(text) == {"a": "b"}

    def test_json_in_bare_fence(self):
        text = '```\n{"a": "b"}\n```'
        assert _parse_json_response(text) == {"a": "b"}

    def test_json_with_surrounding_text(self):
        text = 'Here is the mapping:\n{"a": "b"}\nDone!'
        assert _parse_json_response(text) == {"a": "b"}

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _parse_json_response("")

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _parse_json_response("no json here")


# ---------------------------------------------------------------------------
# prompt_user_approval (mocked stdin)
# ---------------------------------------------------------------------------


class TestPromptUserApproval:
    @patch("builtins.input", side_effect=["", "s", "Custom Name"])
    def test_accept_skip_and_custom(self, _mock_input):
        suggestions = {
            "Alpha": "Mapped Alpha",
            "Beta": "Mapped Beta",
            "Gamma": "Mapped Gamma",
        }
        approved, skipped = prompt_user_approval(suggestions)
        # Alpha -> accepted (Enter), Beta -> skipped, Gamma -> custom
        assert approved == {"Alpha": "Mapped Alpha", "Gamma": "Custom Name"}
        assert skipped == {"Beta"}

    @patch("builtins.input", side_effect=[""])
    def test_single_accept(self, _mock_input):
        approved, skipped = prompt_user_approval({"Raw": "Parsed"})
        assert approved == {"Raw": "Parsed"}
        assert skipped == set()

    @patch("builtins.input", side_effect=["s"])
    def test_single_skip(self, _mock_input):
        approved, skipped = prompt_user_approval({"Raw": "Parsed"})
        assert approved == {}
        assert skipped == {"Raw"}
