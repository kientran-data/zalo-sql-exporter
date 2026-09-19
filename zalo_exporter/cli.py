"""
CLI entry point for Zalo SQL Exporter.

Subcommands:
    discover    Find SQL contacts and persist the list.
    extract     Extract/resume conversations.
    status      Show run status.
    export      Generate CSV and JSON from SQLite.
    (no args)   Run discover + extract (legacy behavior).
"""

import sys
import time
import argparse
from datetime import datetime

from . import config
from .db import ExporterDB
from .ui_driver import (
    find_zalo_window, bring_zalo_to_front, start_hotkey_listener,
    is_stop_requested, scroll_at, get_sidebar_center,
    get_conversation_list, read_open_conversation_name,
)
from .discovery import discover_contacts
from .extraction import extract_conversation
from .export import export_csv, export_json
from .name_matching import normalize_for_match


def _print_banner():
    print("=" * 60)
    print("  ZALO SQL EXPORTER")
    print("  Press F8 at any time to stop safely.")
    print("=" * 60)


def _connect_zalo():
    """Find Zalo window, retrying for up to 30 seconds."""
    for attempt in range(6):
        dlg = find_zalo_window()
        if dlg:
            print("[OK] Connected to Zalo PC.\n")
            return dlg
        if attempt == 0:
            print("Waiting for Zalo PC window... (make sure it's visible, not in system tray)")
        time.sleep(5)
    print("[ERROR] Zalo PC window not found after 30s.")
    print("  - Make sure Zalo PC is open (not just in system tray)")
    print("  - Click the Zalo icon to bring the window up")
    sys.exit(1)


def _click_contact_in_sidebar(dlg, target_name: str) -> bool:
    """
    Click a contact by name in the sidebar.
    Scrolls to find it if not currently visible.
    """
    conv_list = get_conversation_list(dlg)
    if not conv_list:
        return False

    sidebar_x, sidebar_y = get_sidebar_center(dlg)
    target_norm = normalize_for_match(target_name)

    def try_click():
        try:
            for child in conv_list.children(control_type="Text"):
                text = child.window_text()
                if not text:
                    continue
                if normalize_for_match(text) == target_norm:
                    rect = child.rectangle()
                    if rect.width() > 0 and rect.left > 0:
                        child.click_input()
                        return True
        except Exception:
            pass
        return False

    # Try direct click
    if try_click():
        return True

    # Scroll down to find
    for i in range(config.SIDEBAR_MAX_SCROLLS):
        if is_stop_requested():
            return False
        scroll_at(sidebar_x, sidebar_y, 3, "down")
        time.sleep(0.2)
        if try_click():
            return True
        if i >= 200:
            break

    # Scroll back up to find
    for _ in range(config.SIDEBAR_MAX_SCROLLS):
        if is_stop_requested():
            return False
        scroll_at(sidebar_x, sidebar_y, 3, "up")
        time.sleep(0.2)
        if try_click():
            return True

    return False


# =====================================================================
#  Subcommands
# =====================================================================

def cmd_discover(args):
    """Discover SQL contacts and persist them."""
    _print_banner()
    start_hotkey_listener()

    dlg = _connect_zalo()
    db = ExporterDB()

    try:
        # Create or reuse run
        latest_run = db.get_latest_run()
        if latest_run and latest_run["status"] in ("running", "interrupted"):
            run_id = latest_run["run_id"]
            print(f"Resuming run {run_id[:8]}…\n")
        else:
            run_id = db.create_run(discover_method=args.method)
            print(f"New run {run_id[:8]}…\n")

        conversations = discover_contacts(dlg, db, run_id, method=args.method)

        if conversations:
            print(f"\n✓ {len(conversations)} SQL contacts discovered.")
            print("  Run 'python zalo_phase2.py extract' to start extraction.")
        else:
            print("\n✗ No SQL contacts found.")

    finally:
        db.close()


def cmd_extract(args):
    """Extract messages from discovered conversations."""
    _print_banner()
    start_hotkey_listener()

    dlg = _connect_zalo()
    db = ExporterDB()

    try:
        # Find the latest run
        latest_run = db.get_latest_run()
        if not latest_run:
            print("✗ No run found. Run 'python zalo_phase2.py discover' first.")
            return

        run_id = latest_run["run_id"]
        print(f"Run {run_id[:8]}…\n")

        # Get pending conversations
        pending = db.get_pending_conversations(run_id)
        if not pending:
            # Check if there are any conversations at all
            all_convs = db.get_conversations(run_id)
            if not all_convs:
                print("✗ No conversations discovered. Run 'discover' first.")
                return
            print("✓ All conversations already completed.")
            print("  Run 'python zalo_phase2.py export' to generate CSV/JSON.")
            return

        print(f"  {len(pending)} conversations to process.\n")

        bring_zalo_to_front()
        time.sleep(0.5)

        for i, conv in enumerate(pending):
            if is_stop_requested():
                print("\n⚠ Stop requested. Remaining conversations deferred.")
                break

            conv_id = conv["conv_local_id"]
            name = conv["display_name"]

            print(f"\n{'─' * 50}")
            print(f"[{i+1}/{len(pending)}] {name}")

            # Click the contact
            bring_zalo_to_front()
            if not _click_contact_in_sidebar(dlg, name):
                print(f"  ✗ Could not find '{name}' in sidebar. Skipping.")
                db.update_conversation_status(conv_id, "failed",
                                              stop_reason="click_failed",
                                              error_msg="Contact not found in sidebar")
                continue

            time.sleep(config.CLICK_SETTLE)

            # Extract
            obs_count, reason = extract_conversation(dlg, db, conv_id, name)

            if reason == "user_stop":
                print("\n⚠ Stop requested. Remaining conversations deferred.")
                break

        # Update run status
        all_convs = db.get_conversations(run_id)
        all_done = all(c["status"] in ("completed", "failed") for c in all_convs)
        db.update_run_status(run_id, "completed" if all_done else "interrupted")

        # Auto-export
        print(f"\n{'=' * 50}")
        print("Exporting…")
        export_csv(db, run_id)
        export_json(db, run_id)

    finally:
        db.close()


def cmd_status(args):
    """Show run status."""
    db = ExporterDB()
    try:
        latest_run = db.get_latest_run()
        if not latest_run:
            print("No runs found.")
            return

        run_id = latest_run["run_id"]
        summary = db.get_run_summary(run_id)
        run = summary["run"]

        print(f"Run:    {run_id[:8]}…")
        print(f"Status: {run['status']}")
        print(f"Started: {run['started_at']}")
        print(f"Method: {run.get('discover_method', 'N/A')}")
        print(f"Total observations: {summary['total_observations']}")
        print()

        convs = summary["conversations"]
        if convs:
            print(f"Conversations ({len(convs)}):")
            for c in convs:
                status_icon = {
                    "pending": "○",
                    "in_progress": "◐",
                    "partial": "◑",
                    "completed": "●",
                    "failed": "✗",
                }.get(c["status"], "?")
                print(f"  {status_icon} {c['display_name']}: "
                      f"{c['message_count']} obs, "
                      f"{c['scroll_count']} scrolls, "
                      f"status={c['status']}"
                      + (f", reason={c['stop_reason']}" if c['stop_reason'] else ""))
        else:
            print("No conversations discovered yet.")
    finally:
        db.close()


def cmd_export(args):
    """Export data from SQLite to CSV/JSON."""
    db = ExporterDB()
    try:
        latest_run = db.get_latest_run()
        if not latest_run:
            print("No runs found.")
            return

        run_id = latest_run["run_id"]
        fmt = args.format

        if fmt in ("csv", "all"):
            export_csv(db, run_id, args.output if fmt == "csv" else None)
        if fmt in ("json", "all"):
            export_json(db, run_id, args.output if fmt == "json" else None)

    finally:
        db.close()


def cmd_run(args):
    """Default: single-pass discover + extract."""
    _print_banner()
    start_hotkey_listener()

    dlg = _connect_zalo()
    db = ExporterDB()

    try:
        if args.method != "scroll":
            print("Warning: Single-pass mode only supports --method scroll. Ignoring method.")
            
        # Create run
        run_id = db.create_run(discover_method="single_pass")
        print(f"Run {run_id[:8]} (Single-Pass Mode)...\n")
        
        from .name_matching import matches_sql
        from .discovery import _read_sidebar_names
        
        conv_list = get_conversation_list(dlg)
        if not conv_list:
            print("[ERROR] Cannot find conversationList.")
            return

        sidebar_x, sidebar_y = get_sidebar_center(dlg)
        
        # Scroll sidebar to top
        print("Scrolling sidebar to top...")
        bring_zalo_to_front()
        for _ in range(100):
            if is_stop_requested():
                break
            scroll_at(sidebar_x, sidebar_y, 5, "up")
            time.sleep(0.02)
        time.sleep(1)
        
        processed_norms = set()
        no_new_scrolls = 0
        total_sidebar_scrolls = 0
        
        while no_new_scrolls < config.SIDEBAR_NO_NEW_LIMIT and total_sidebar_scrolls < config.SIDEBAR_MAX_SCROLLS:
            if is_stop_requested():
                print("\nStop requested.")
                db.update_run_status(run_id, "interrupted")
                break
            
            found_new_in_viewport = False
            
            # Re-acquire conv_list each iteration (it can go stale after extraction)
            try:
                conv_list = get_conversation_list(dlg)
                if not conv_list:
                    print("  [WARN] Lost conversationList, reconnecting...")
                    dlg = _connect_zalo()
                    conv_list = get_conversation_list(dlg)
                    if not conv_list:
                        print("  [ERROR] Cannot recover conversationList.")
                        break
                    sidebar_x, sidebar_y = get_sidebar_center(dlg)
            except Exception as e:
                print(f"  [WARN] Error getting conversationList: {e}")
                time.sleep(1)
                try:
                    dlg = _connect_zalo()
                    conv_list = get_conversation_list(dlg)
                    sidebar_x, sidebar_y = get_sidebar_center(dlg)
                except Exception:
                    print("  [ERROR] Cannot recover. Stopping.")
                    break
            
            # Read sidebar children directly — find SQL matches and click them
            from .name_matching import is_pua_only, is_sidebar_date
            try:
                children = conv_list.children(control_type="Text")
                if not children:
                    children = conv_list.descendants(control_type="Text")
            except Exception:
                children = []
            
            # Debug: on the first iteration, print what we see
            if total_sidebar_scrolls == 0:
                try:
                    ei = conv_list.element_info
                    print(f"  [DEBUG] conv_list automation_id='{ei.automation_id}', "
                          f"type='{ei.control_type}', "
                          f"visible={conv_list.is_visible()}")
                except Exception as e:
                    print(f"  [DEBUG] conv_list info error: {e}")
                rect = conv_list.rectangle()
                print(f"  [DEBUG] conv_list rect: left={rect.left}, top={rect.top}, "
                      f"w={rect.width()}, h={rect.height()}")
                print(f"  [DEBUG] Text children count: {len(children)}")
                
                # Show first 10 children with their filter status
                for i, child in enumerate(children[:10]):
                    try:
                        text = child.window_text()
                        r = child.rectangle()
                        pua = is_pua_only(text) if text else False
                        sdate = is_sidebar_date(text) if text else False
                        sql = matches_sql(text) if text else False
                        print(f"  [DEBUG]   [{i}] text='{(text or '')[:40]}' "
                              f"rect=({r.left},{r.top},{r.width()},{r.height()}) "
                              f"pua={pua} date={sdate} sql={sql}")
                    except Exception as e:
                        print(f"  [DEBUG]   [{i}] ERROR: {e}")
            
            sql_elements = []  # [(name, element), ...]
            last_row_top = -1000
            
            skipped_empty = 0
            skipped_pua = 0
            skipped_date = 0
            skipped_rect = 0
            skipped_row = 0
            passed_filter = 0
            
            for child in children:
                try:
                    text = child.window_text()
                    if not text or not text.strip():
                        skipped_empty += 1
                        continue
                    if is_pua_only(text):
                        skipped_pua += 1
                        continue
                    if is_sidebar_date(text):
                        skipped_date += 1
                        continue
                    rect = child.rectangle()
                    if rect.width() <= 0:
                        skipped_rect += 1
                        continue
                    if abs(rect.top - last_row_top) < 5:
                        skipped_row += 1
                        continue
                    last_row_top = rect.top
                    passed_filter += 1
                    
                    norm = normalize_for_match(text)
                    if matches_sql(text) and norm not in processed_norms:
                        sql_elements.append((text, norm, child))
                except Exception:
                    continue
            
            # Debug: print filter stats on first iteration
            if total_sidebar_scrolls == 0:
                print(f"  [DEBUG] Filter stats: empty={skipped_empty}, pua={skipped_pua}, "
                      f"date={skipped_date}, rect={skipped_rect}, row_dedup={skipped_row}, "
                      f"passed={passed_filter}, sql_match={len(sql_elements)}")
            
            for name, norm, element in sql_elements:
                if is_stop_requested():
                    break
                    
                processed_norms.add(norm)
                
                # Skip if already completed in a previous run
                if db.is_already_completed(norm):
                    print(f"  >> Skipping '{name}' (already completed)")
                    continue
                
                found_new_in_viewport = True
                
                # 1. Add to DB
                conv_id = db.add_conversation(run_id, name, norm)
                
                print(f"\n{'=' * 50}")
                print(f"[{len(processed_norms)}] Found: {name}")
                
                # 2. Click the element directly (it's already visible)
                click_ok = False
                try:
                    bring_zalo_to_front()
                    element.click_input()
                    click_ok = True
                except Exception as e:
                    print(f"  [WARN] Direct click failed ({e}), trying search...")
                    # Fallback: try the old search method
                    click_ok = _click_contact_in_sidebar(dlg, name)
                
                if not click_ok:
                    print(f"  [FAIL] Could not click '{name}'. Skipping.")
                    db.update_conversation_status(conv_id, "failed", stop_reason="click_failed")
                    continue
                    
                time.sleep(config.CLICK_SETTLE)
                
                # 3. Extract immediately
                try:
                    obs_count, reason = extract_conversation(dlg, db, conv_id, name)
                except Exception as e:
                    print(f"  [ERROR] Extraction error: {e}")
                    db.update_conversation_status(conv_id, "failed", stop_reason=str(e)[:100])
                    reason = "error"
                
                if reason == "user_stop":
                    break
                    
                # 4. Give UI time to settle before next sidebar read
                bring_zalo_to_front()
                time.sleep(0.5)
                    
            # Reset scroll counter if we found ANY SQL contact in this viewport
            # (even already-completed ones), because we need to keep scrolling
            # past them to reach uncompleted contacts further down.
            if sql_elements or found_new_in_viewport:
                no_new_scrolls = 0
            else:
                no_new_scrolls += 1
                
            if is_stop_requested():
                break
                
            # Scroll sidebar down
            bring_zalo_to_front()
            scroll_at(sidebar_x, sidebar_y, config.SIDEBAR_SCROLL_TICKS, "down")
            time.sleep(0.2)
            total_sidebar_scrolls += 1
            
            if total_sidebar_scrolls % 20 == 0:
                print(f"  Scanning sidebar... #{total_sidebar_scrolls}, processed {len(processed_norms)}")

        # Finalize
        if not is_stop_requested():
            print(f"\nFinished scanning sidebar. Found {len(processed_norms)} contacts.")
        
        all_convs = db.get_conversations(run_id)
        all_done = all(c["status"] in ("completed", "failed") for c in all_convs)
        db.update_run_status(run_id, "completed" if all_done else "interrupted")

        print(f"\n{'=' * 50}")
        print("Exporting...")
        export_csv(db, run_id)
        export_json(db, run_id)

    finally:
        db.close()


# =====================================================================
#  Main
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="zalo_phase2",
        description="Zalo SQL Exporter — extract chat history from Zalo PC.",
    )
    parser.add_argument(
        "--method", choices=["scroll", "search", "both"],
        default="scroll",
        help="Discovery method for finding SQL contacts (default: scroll).",
    )

    subparsers = parser.add_subparsers(dest="command")

    # discover
    p_discover = subparsers.add_parser("discover", help="Find SQL contacts.")
    p_discover.add_argument("--method", choices=["scroll", "search", "both"],
                            default="scroll")

    # extract
    p_extract = subparsers.add_parser("extract", help="Extract/resume conversations.")

    # status
    p_status = subparsers.add_parser("status", help="Show run status.")

    # export
    p_export = subparsers.add_parser("export", help="Export CSV/JSON from SQLite.")
    p_export.add_argument("--format", choices=["csv", "json", "all"],
                          default="all")
    p_export.add_argument("--output", help="Output file path.")

    args = parser.parse_args()

    if args.command == "discover":
        cmd_discover(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "export":
        cmd_export(args)
    else:
        # No subcommand: run discover + extract
        cmd_run(args)
