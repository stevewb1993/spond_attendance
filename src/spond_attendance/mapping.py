"""Session name mapping: raw names → canonical parsed names."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import pandas as pd

SKIP_SENTINEL = "__SKIP__"


def load_name_mappings(path: Path) -> dict[str, str]:
    """Load session_name_mappings.csv into a raw→parsed dict.

    Returns an empty dict if the file doesn't exist.
    """
    if not path.exists():
        return {}
    mappings: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mappings[row["raw_session_name"]] = row["parsed_session_name"]
    return mappings


def save_name_mappings(path: Path, mappings: dict[str, str]) -> None:
    """Write mappings dict back to session_name_mappings.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["raw_session_name", "parsed_session_name"])
        writer.writeheader()
        for raw, parsed in sorted(mappings.items()):
            writer.writerow({"raw_session_name": raw, "parsed_session_name": parsed})


def load_canonical_names(types_path: Path) -> set[str]:
    """Load the set of canonical session names from session_types.csv."""
    if not types_path.exists():
        return set()
    df = pd.read_csv(types_path)
    return set(df["session_name"].dropna().unique())


def find_unmapped_names(
    session_names: set[str],
    mappings: dict[str, str],
    known_canonical: set[str],
) -> set[str]:
    """Find session names that have no mapping and aren't already canonical.

    A name is "unmapped" if it:
    - Is not a key in the explicit mappings dict, AND
    - Is not already a known canonical name (from session_types.csv)
    """
    return session_names - set(mappings.keys()) - known_canonical


def suggest_mappings(
    unmapped: set[str],
    known_canonical: set[str],
) -> dict[str, str]:
    """Use the Claude CLI to suggest parsed names for unmapped raw session names.

    Requires the `claude` CLI (Claude Code) to be installed and authenticated.
    Returns a dict of raw_name → suggested_parsed_name.
    """
    import subprocess

    canonical_list = sorted(known_canonical)
    unmapped_list = sorted(unmapped)

    prompt = f"""You are helping normalize session names for a triathlon club's attendance tracking system.

Here are the known canonical session names:
{json.dumps(canonical_list, indent=2)}

The following raw session names from Spond exports don't match any known canonical name.
For each one, suggest the most likely canonical name it should map to.
If a name is genuinely new (not a variant of any existing name), suggest a clean canonical name for it.

Raw session names to map:
{json.dumps(unmapped_list, indent=2)}

Respond with ONLY a JSON object mapping each raw name to its suggested canonical name. No other text.
Example: {{"STV Swim!": "STV Swim", "New Session Type": "New Session Type"}}"""

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr.strip()}")

    return _parse_json_response(result.stdout)


def _parse_json_response(text: str) -> dict[str, str]:
    """Extract and parse a JSON object from Claude's response.

    Handles cases where the response includes markdown fences or
    surrounding text around the JSON.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Find the outermost { ... } block
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from Claude response:\n{text[:500]}")


def prompt_user_approval(
    suggestions: dict[str, str],
) -> tuple[dict[str, str], set[str]]:
    """Interactively prompt the user to approve each suggested mapping.

    For each suggestion, the user can:
    - Press Enter to accept
    - Type 's' to skip
    - Type an alternative parsed name

    Returns (approved_mappings, skipped_keys).
    """
    approved: dict[str, str] = {}
    skipped: set[str] = set()
    total = len(suggestions)

    for i, (raw, suggested) in enumerate(sorted(suggestions.items()), 1):
        response = input(
            f'  ({i}/{total}) "{raw}" → "{suggested}" [Enter=accept, s=skip, or type alternative]: '
        )
        response = response.strip()

        if response == "":
            approved[raw] = suggested
        elif response.lower() == "s":
            skipped.add(raw)
        else:
            approved[raw] = response

    return approved, skipped


def load_session_types(path: Path) -> dict[str, str]:
    """Load session_types.csv into a name→category dict."""
    if not path.exists():
        return {}
    types: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            types[row["session_name"]] = row["category"]
    return types


def save_session_types(path: Path, types: dict[str, str]) -> None:
    """Write session types dict back to session_types.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["session_name", "category"])
        writer.writeheader()
        for name, category in sorted(types.items()):
            writer.writerow({"session_name": name, "category": category})


def suggest_categories(
    uncategorized: set[str],
    existing_types: dict[str, str],
) -> dict[str, str]:
    """Use the Claude CLI to suggest categories for uncategorized session names.

    Returns a dict of session_name → suggested_category.
    """
    import subprocess

    categories = sorted(set(existing_types.values()))
    examples = {name: cat for name, cat in sorted(existing_types.items())[:15]}
    uncategorized_list = sorted(uncategorized)

    prompt = f"""You are helping categorize session names for a triathlon club's attendance tracking system.

The available categories are:
{json.dumps(categories, indent=2)}

Here are some examples of existing categorizations:
{json.dumps(examples, indent=2)}

Assign a category to each of the following session names.
Use one of the existing categories above. Use "Other" for social events, one-offs, or anything that doesn't fit.

Session names to categorize:
{json.dumps(uncategorized_list, indent=2)}

Respond with ONLY a JSON object mapping each session name to its category. No other text.
Example: {{"STV Swim": "Swim", "Christmas Party": "Other"}}"""

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr.strip()}")

    return _parse_json_response(result.stdout)


def apply_name_mappings(df: pd.DataFrame, mappings: dict[str, str]) -> pd.DataFrame:
    """Replace session_name values using the mappings dict.

    Names not in the dict are left unchanged. Entries with SKIP_SENTINEL
    as the value are ignored (the original name is kept).
    """
    active = {k: v for k, v in mappings.items() if v != SKIP_SENTINEL}
    if not active:
        return df
    df = df.copy()
    df["session_name"] = df["session_name"].replace(active)
    return df
