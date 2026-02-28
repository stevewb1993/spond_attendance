#!/bin/bash
# PostToolUse hook: run ruff + ty after editing Python files

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check Python files
if [[ "$FILE_PATH" != *.py ]]; then
  exit 0
fi

# Collect issues
ISSUES=""

# Ruff lint
RUFF_OUTPUT=$(uv run ruff check "$FILE_PATH" 2>&1)
if [[ $? -ne 0 ]]; then
  ISSUES+="ruff check:\n$RUFF_OUTPUT\n\n"
fi

# Ruff format
FORMAT_OUTPUT=$(uv run ruff format --check "$FILE_PATH" 2>&1)
if [[ $? -ne 0 ]]; then
  ISSUES+="ruff format:\n$FORMAT_OUTPUT\n\n"
fi

# ty type check
TY_OUTPUT=$(uv run ty check "$FILE_PATH" 2>&1)
if [[ $? -ne 0 ]]; then
  ISSUES+="ty check:\n$TY_OUTPUT\n\n"
fi

if [[ -n "$ISSUES" ]]; then
  REASON=$(echo -e "$ISSUES" | jq -Rs .)
  echo "{\"decision\": \"block\", \"reason\": $REASON}"
  exit 2
fi

exit 0
