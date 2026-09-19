# Zalo SQL Exporter

Export chat history from Zalo PC for contacts whose custom nickname contains "sql".

## Requirements

- Windows 10/11
- Zalo PC installed and logged in
- Python 3.11+

## Setup

```powershell
cd c:\Users\Admin\Documents\work\kien\zalo-sql-exporter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pywinauto
```

## Commands

```powershell
# Full run: discover SQL contacts + extract all conversations
python zalo_phase2.py

# Step-by-step workflow:
python zalo_phase2.py discover           # Find SQL contacts in sidebar
python zalo_phase2.py extract            # Extract/resume conversations
python zalo_phase2.py status             # Show progress
python zalo_phase2.py export             # Regenerate CSV + JSON from SQLite
python zalo_phase2.py export --format csv --output custom.csv

# Transform raw CSV into a clean conversational format
python transform_zalo_csv.py --input "zalo_all_sql_history.csv" --output "zalo_messages_clean.csv"
```

### Discovery methods

```powershell
python zalo_phase2.py --method scroll    # Scroll entire sidebar (default)
python zalo_phase2.py --method search    # Use Zalo's search bar
python zalo_phase2.py --method both      # Try search first, fall back to scroll
```

## Stopping

**Press F8** at any time to stop safely. The script will:
1. Finish the current database commit.
2. Mark the conversation as partial.
3. Stop reclaiming foreground focus (so you regain control).

Data committed before the stop is preserved. Run `extract` again to resume.

Do **not** need to use Ctrl+C — the F8 hotkey works from any window.

## Resuming after crash/stop

```powershell
python zalo_phase2.py status     # Check what was completed
python zalo_phase2.py extract    # Resume from where it left off
```

The SQLite database (`zalo_exporter.db`) stores all progress. Completed
conversations are skipped on resume. Partial conversations restart extraction.

## Output files

| File | Description |
|------|-------------|
| `zalo_exporter.db` | SQLite database with all raw observations |
| `zalo_all_sql_history.csv` | CSV export (UTF-8 BOM for Excel) |
| `zalo_all_sql_history.json` | JSON export |
| `zalo_messages_clean.csv` | Cleaned conversational CSV (created by transform script) |

## How it works

1. **Discovery**: Scrolls the Zalo sidebar (or uses search) to find contacts
   with "sql" in their nickname. Names are Unicode-normalized for matching.

2. **Extraction**: For each contact, clicks to open the conversation, scrolls
   to the bottom, then scrolls upward reading visible messages. Uses adaptive
   waits (polls for content stability instead of fixed sleeps) for speed.

3. **Persistence**: Each viewport batch is committed to SQLite immediately.
   Crashes lose at most one viewport of data.

4. **Export**: CSV and JSON are generated from the SQLite database on demand.

5. **Transformation**: The `transform_zalo_csv.py` script cleans the raw CSV export into a readable conversational format, grouping by conversation, reconstructing oldest-to-newest order, extracting dates and times into separate columns, and mapping senders.

## Troubleshooting

**"Zalo PC not found"**: Make sure Zalo is open. The window title must be
exactly "Zalo".

**Mouse scrolling in wrong window**: The script calls `SetForegroundWindow`
to bring Zalo to front. Don't click other windows while it runs.

**Missed contacts**: Try `--method both` to combine search and scroll
discovery. Run `status` to see what was found.

**Slow extraction**: The adaptive wait system should be significantly faster
than the old fixed 1.5s sleep. If loading is slow, the script backs off
automatically.

## Debug

```powershell
python dump_zalo_ui.py          # Dump Zalo's UI tree to zalo_ui_tree.txt
```

## Data privacy

All data stays local. The `.gitignore` excludes databases, CSVs, JSONs,
and UI dumps from version control.
