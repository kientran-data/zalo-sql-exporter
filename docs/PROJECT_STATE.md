# Project State — Zalo SQL Exporter

Last updated: 2026-09-21

## Implementation status

| Feature | Status | Notes |
|---------|--------|-------|
| Modular architecture | ✅ Implemented | 8 modules in `zalo_exporter/` |
| SQLite persistence | ✅ Implemented | WAL mode, per-batch commits |
| Name normalization | ✅ Implemented + tested | NBSP, NFC, casefold |
| Sidebar scroll discovery | ✅ Implemented | Row-pattern parsing to distinguish names from previews |
| Search-bar discovery | ✅ Implemented | Tested and functional |
| Adaptive scroll waits | ✅ Implemented | Polls for stability vs fixed 1.5s sleep |
| F8 stop hotkey | ✅ Implemented | Background thread with GetAsyncKeyState |
| Conversation verification | ✅ Implemented | Checks chatViewContainer name before extraction |
| Crash-safe resume | ✅ Implemented | Checkpoint in same transaction as data |
| CLI subcommands | ✅ Implemented | discover, extract, status, export |
| CSV/JSON export | ✅ Implemented | From SQLite, not memory |
| Analysis data pipeline | ✅ Implemented | `format_for_analysis.py`: 2-pass dedup, noise/reaction filters |
| Unit tests | ✅ 33/33 passing | Core exporter, database, overlap reconciliation & analysis formatter |

## Technical decisions

1. **Screen-coordinate scrolling**: `conversationList` has virtual bounds
   (T=-32415, B=27743). We use `ctypes.windll.user32.mouse_event` at
   real screen coordinates calculated from the main window rectangle.

2. **Per-batch commits**: Each viewport read is committed atomically with
   its checkpoint. This means at most one viewport of data is lost on crash.

3. **No observation deletion**: Duplicates are flagged, never removed from SQLite.
   This allows re-running dedup logic or refining filtering downstream.

4. **Sidebar name parsing**: The conversationList's Text children repeat
   in groups: [name, date, pua_icon, preview, ...]. We identify names by
   filtering out dates, PUA icons, and message previews (which start with
   "You:" and appear below the name in the same row).

5. **Two-pass deduplication in analysis pipeline (`format_for_analysis.py`)**:
   - **Pass 1 (Block overlap)**: Checks for repeated blocks of up to 40 messages to catch identical consecutive viewport slices caused by scroll overlap.
   - **Pass 2 (Sliding-window lookback)**: Looks back 60 messages within a conversation to catch non-adjacent duplicate messages produced by batch boundary artifacts and UI virtualization. Short messages (<= 3 characters, e.g., "ok", "dạ") are exempt from window deduplication unless strictly consecutive.

6. **Noise and reaction filtering**: Emoticon codes (`/-strong`, `/-heart`, `:>`, `:o`, `:-((`, etc.) and system UI noise (`photo`, `sticker`, `chưa có tin nhắn nào`, etc.) are filtered out so that `zalo_clean.csv` contains purely readable dialogue.

7. **Date and time propagation**: Inferred dates from date markers and times from time markers are mapped directly onto the corresponding message records.

## Verified behavior (unit tests)

- `[SQL] Vũ Đức Thanh` matches ✓
- `SQL_Kien` matches ✓
- `khach_hang_sql_1` matches ✓
- `[sql] Lan` matches ✓
- `SQL_K9\xa0GIA\xa0NHƯ\xa0HÀ\xa0HÀ` matches ✓
- Non-SQL names correctly excluded ✓
- Two consecutive "ok" messages preserved in overlap reconciliation ✓
- Two "ok" with identical timestamps at batch boundary preserved ✓
- Committed data survives connection close/reopen ✓
- Checkpoint never ahead of committed observations ✓
- Date & time regex and format normalizations ✓
- Noise and reaction classification rules ✓

## Recent Updates & Bug Fixes

### 2026-09-21: Analysis formatting pipeline & Dedup improvements
- Implemented `format_for_analysis.py` providing complete end-to-end data transformation from raw SQLite export into `zalo_clean.csv`.
- Filtered out Zalo reaction icons and emoticons (`/-strong`, `/-heart`, `:>`, etc.).
- Developed two-pass deduplication: resolved multi-row batch overlap and non-adjacent duplicates across scroll boundaries (reduced cleaned message rows from ~72k down to 53,570 clean rows).
- Added test suite `tests/test_format_for_analysis.py` (all 33 unit tests pass).

### 2026-09-19: UI crawler robustness fixes
- **Nested Labels UI**: Fixed issue where Zalo hides standard `conversationList` when viewing the "Labels" (Phân loại) tab. Scans for any visible `Table` or `List` on the left sidebar and uses `.descendants` to find text nodes.
- **Negative Coordinates**: Fixed issue where contacts were ignored if Zalo window was on a secondary monitor with negative coordinates (`rect.left < 0`).
- **Early Termination**: Fixed bug where skipping already-completed contacts prematurely terminated the sidebar scan.

## Local data investigation (2026-09-17)

**Result: Direct data extraction is NOT feasible for messages.**

- Zalo PC data is at `C:\Users\Admin\AppData\Roaming\ZaloData`
- **Message text is NOT stored locally** — Zalo fetches from server on demand
- `.calf` files are proprietary app bundles, not databases
- No SQLite message DB exists anywhere
- **Contact aliases ARE readable** from LevelDB Local Storage:
  `{"aliasName":"SQL_04_2025 Le Gia Hau"}` found in `038077.ldb`
- Contact UIDs and real names (`zName`) readable from `000005.ldb`
- Encryption keys exist (`enk`, `viewer_key`) but moot since message data isn't cached
- **UI extraction remains the only viable method for message content**

## Next steps

1. Downstream text analytics and metric extraction on `zalo_clean.csv`.
2. Optional: Add CLI flag in `zalo_phase2.py export --clean` to automatically run `format_for_analysis.py`.

