# Project State — Zalo SQL Exporter

Last updated: 2026-09-17

## Implementation status

| Feature | Status | Notes |
|---------|--------|-------|
| Modular architecture | ✅ Implemented | 8 modules in `zalo_exporter/` |
| SQLite persistence | ✅ Implemented | WAL mode, per-batch commits |
| Name normalization | ✅ Implemented + tested | NBSP, NFC, casefold, 24 unit tests pass |
| Sidebar scroll discovery | ✅ Implemented | Row-pattern parsing to distinguish names from previews |
| Search-bar discovery | ✅ Implemented | **Unverified** — needs manual test |
| Adaptive scroll waits | ✅ Implemented | Polls for stability vs fixed 1.5s sleep |
| F8 stop hotkey | ✅ Implemented | Background thread with GetAsyncKeyState |
| Conversation verification | ✅ Implemented | Checks chatViewContainer name before extraction |
| Crash-safe resume | ✅ Implemented | Checkpoint in same transaction as data |
| CLI subcommands | ✅ Implemented | discover, extract, status, export |
| CSV/JSON export | ✅ Implemented | From SQLite, not memory |
| Unit tests | ✅ 24/24 passing | Name matching, DB, overlap reconciliation |

## Technical decisions

1. **Screen-coordinate scrolling**: `conversationList` has virtual bounds
   (T=-32415, B=27743). We use `ctypes.windll.user32.mouse_event` at
   real screen coordinates calculated from the main window rectangle.

2. **Per-batch commits**: Each viewport read is committed atomically with
   its checkpoint. This means at most one viewport of data is lost on crash.

3. **No observation deletion**: Duplicates are flagged, never removed.
   This allows re-running dedup logic if bugs are found.

4. **Sidebar name parsing**: The conversationList's Text children repeat
   in groups: [name, date, pua_icon, preview, ...]. We identify names by
   filtering out dates, PUA icons, and message previews (which start with
   "You:" and appear below the name in the same row).

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

## Unverified (requires Zalo running)

- Whether Zalo search matches custom nicknames.
- Whether sidebar row-pattern parsing works across all Zalo versions.
- Actual extraction speed improvement (estimated 4× from adaptive waits).
- F8 hotkey responsiveness during extraction.
- Resume after mid-conversation stop.

## Recent Bug Fixes (2026-09-19)

- **Nested Labels UI**: Fixed issue where Zalo hides the standard `conversationList` when viewing the "Labels" (Phân loại) tab. The script now scans for any visible `Table` or `List` on the left sidebar and uses `.descendants` to find text nodes, preventing it from missing contacts in custom labels.
- **Negative Coordinates**: Fixed issue where contacts were ignored if the Zalo window was on a secondary monitor with negative coordinates (`rect.left < 0`).
- **Early Termination**: Fixed a bug where skipping already-completed contacts caused the `no_new_scrolls` counter to increment and terminate the scan prematurely. It now resets the counter as long as ANY SQL contact (completed or not) is found in the viewport.

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

1. Run `python zalo_phase2.py` with Zalo open to validate end-to-end.
2. Test `--method search` to determine if search matches nicknames.
3. Measure extraction time for a representative conversation.
4. Optionally: read LevelDB aliases to pre-populate contact list with verified UIDs.

