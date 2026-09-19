# Zalo SQL Exporter — Project Rules

## Purpose

Extract Zalo PC chat history for contacts whose custom nickname contains "sql",
using Windows UI Automation (pywinauto) to read the accessibility tree.

## Module map

```
zalo_exporter/
├── cli.py            # CLI entry point, argparse subcommands
├── config.py         # All tunable constants
├── db.py             # SQLite schema, reads, writes, transactions
├── discovery.py      # Find SQL contacts (search + sidebar scroll)
├── extraction.py     # Read messages from open conversations
├── export.py         # Generate CSV/JSON from SQLite
├── name_matching.py  # Unicode normalization, SQL matching
└── ui_driver.py      # Window management, scrolling, F8 hotkey

transform_zalo_csv.py # Transform raw CSV into readable conversational format
```

Entry point: `zalo_phase2.py` → `zalo_exporter.cli.main()`.

## Key files to read first

1. `AGENTS.md` (this file) — architecture overview.
2. `zalo_exporter/config.py` — all tunable constants.
3. `zalo_exporter/db.py` — database schema and commit logic.
4. `zalo_exporter/cli.py` — command flow.

## Data integrity rules

- **Never delete observations.** Flag duplicates with `is_duplicate=1`.
- **Commit per viewport batch**, not per message or per conversation.
- **Checkpoint stored in same transaction** as observations.
- **WAL mode** for crash safety.
- **Do not interact with the Zalo message composer** (`richInput`).
- **Verify open conversation name** before assigning captured messages.

## Validation approach

Run `python -m unittest tests.test_core -v` to validate:
- Name matching for all required patterns.
- Database commit/checkpoint consistency.
- Crash safety (close + reopen preserves data).
- Overlap reconciliation preserving consecutive identical messages.

## Known limitations

- **No Zalo message IDs**: The UI tree exposes no message IDs or conversation
  IDs. All identifiers are locally generated UUIDs.
- **Virtualized UI**: Zalo only renders visible elements. Off-screen content
  has zero-width rectangles. We can only read what's on screen.
- **Sender detection by position**: "Me" vs "Other" is determined by whether
  the element's X coordinate is to the right or left of the chat center.
  This is a heuristic based on Zalo's layout.
- **Search bar matching**: Not verified whether Zalo's search matches custom
  nicknames. Default discovery method is sidebar scroll.
- **Partial history**: Cannot confirm reaching the absolute beginning of
  conversation history. Results marked accordingly.
- **Screen coordinates for scrolling**: Must use real screen coordinates
  (not UIA control coordinates) because `conversationList` has virtualized
  bounds spanning ~60,000 pixels.
