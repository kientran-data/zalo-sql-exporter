"""
Discover Zalo conversations whose name matches 'sql'.

Two strategies:
  1. Search-bar approach: type 'sql' into the sidebar search box.
  2. Sidebar-scroll approach: scroll through the entire sidebar.

Each strategy produces a list of display names.  Names are normalized,
de-duplicated, and persisted to the database.
"""

import time

from . import config
from .name_matching import normalize_for_match, matches_sql, is_pua_only, is_sidebar_date
from .ui_driver import (
    bring_zalo_to_front, scroll_at, get_sidebar_center,
    get_conversation_list, get_search_input, is_stop_requested,
)
from .db import ExporterDB


def _read_sidebar_names(conv_list) -> list[str]:
    """
    Read contact names from the current viewport of conversationList.

    The sidebar's Text children follow a repeating pattern per entry:
        [name] [date] [pua_icon] [message_preview] …

    We identify names by:
      - Non-empty, non-PUA text.
      - Not matching date patterns.
      - Having a distinct vertical position (new row).

    Returns a list of candidate name strings.
    """
    names = []
    try:
        children = conv_list.children(control_type="Text")
    except Exception:
        return names

    last_row_top = -1000  # Track vertical row boundaries

    for child in children:
        try:
            text = child.window_text()
            if not text or not text.strip():
                continue
            if is_pua_only(text):
                continue

            rect = child.rectangle()

            # Skip invisible / off-screen elements
            if rect.width() <= 0:
                continue

            # Skip dates (DD/MM/YY or DD/MM/YYYY)
            if is_sidebar_date(text):
                continue

            # Skip message previews: they follow the name in the same row.
            # A "new row" starts when rect_top jumps by ≥ 40px from last name.
            if rect.top - last_row_top < 40:
                continue

            # Skip known non-name prefixes (message preview indicators)
            stripped = text.strip()
            if stripped.startswith("You:\xa0") or stripped.startswith("You: "):
                continue

            # This is likely a contact name
            names.append(text)
            last_row_top = rect.top

        except Exception:
            continue

    return names


def discover_by_scroll(dlg, db: ExporterDB, run_id: str) -> list[str]:
    """
    Discover SQL contacts by scrolling through the entire sidebar.

    Returns list of display names found.
    """
    print("  Strategy: sidebar scroll")

    conv_list = get_conversation_list(dlg)
    if not conv_list:
        print("  ✗ Cannot find conversationList.")
        return []

    sidebar_x, sidebar_y = get_sidebar_center(dlg)
    found_names: dict[str, str] = {}  # normalized → original

    # Scroll to top
    print("  Scrolling sidebar to top…")
    bring_zalo_to_front()
    for _ in range(100):
        if is_stop_requested():
            break
        scroll_at(sidebar_x, sidebar_y, 5, "up")
        time.sleep(0.02)
    time.sleep(1)

    # Initial scan
    for name in _read_sidebar_names(conv_list):
        norm = normalize_for_match(name)
        if matches_sql(name) and norm not in found_names:
            found_names[norm] = name

    print(f"  Initial viewport: {len(found_names)} SQL contacts.")

    # Scroll down, scanning periodically
    no_new = 0
    for i in range(config.SIDEBAR_MAX_SCROLLS):
        if is_stop_requested():
            print("  ⚠ Stop requested.")
            break

        scroll_at(sidebar_x, sidebar_y, config.SIDEBAR_SCROLL_TICKS, "down")
        time.sleep(0.12)

        if (i + 1) % 3 == 0:
            prev_count = len(found_names)
            for name in _read_sidebar_names(conv_list):
                norm = normalize_for_match(name)
                if matches_sql(name) and norm not in found_names:
                    found_names[norm] = name

            if len(found_names) > prev_count:
                no_new = 0
                print(f"  Scroll #{i+1}: found {len(found_names)} SQL contacts (+{len(found_names)-prev_count})")
            else:
                no_new += 1

            if no_new >= config.SIDEBAR_NO_NEW_LIMIT:
                print(f"  No new contacts after {no_new} scans. Done.")
                break

        if (i + 1) % 50 == 0 and no_new < config.SIDEBAR_NO_NEW_LIMIT:
            print(f"  Scanning… #{i+1}, {len(found_names)} SQL contacts so far")

    # Scroll back to top
    print("  Scrolling sidebar back to top…")
    for _ in range(150):
        if is_stop_requested():
            break
        scroll_at(sidebar_x, sidebar_y, 5, "up")
        time.sleep(0.02)
    time.sleep(0.5)

    return list(found_names.values())


def discover_by_search(dlg, db: ExporterDB, run_id: str) -> list[str]:
    """
    Discover SQL contacts using the search bar.

    NOTE: This needs manual verification that Zalo search matches
    custom nicknames.  If it doesn't, fall back to sidebar scroll.
    """
    print("  Strategy: search bar")

    search_input = get_search_input(dlg)
    if not search_input:
        print("  ✗ Cannot find search input. Falling back to scroll.")
        return []

    bring_zalo_to_front()
    time.sleep(0.3)

    try:
        # Click and type search query
        search_input.click_input()
        time.sleep(0.3)
        search_input.type_keys("sql", with_spaces=True)
        time.sleep(config.SEARCH_RESULT_WAIT)

        # Read results from the conversation list
        conv_list = get_conversation_list(dlg)
        if not conv_list:
            print("  ✗ Cannot find conversationList after search.")
            return []

        found_names: dict[str, str] = {}
        for name in _read_sidebar_names(conv_list):
            norm = normalize_for_match(name)
            if norm not in found_names:
                found_names[norm] = name

        print(f"  Search returned {len(found_names)} results.")

        # Scroll search results to find more
        sidebar_x, sidebar_y = get_sidebar_center(dlg)
        no_new = 0
        for i in range(50):
            if is_stop_requested():
                break
            scroll_at(sidebar_x, sidebar_y, 3, "down")
            time.sleep(0.3)
            prev = len(found_names)
            for name in _read_sidebar_names(conv_list):
                norm = normalize_for_match(name)
                if norm not in found_names:
                    found_names[norm] = name
            if len(found_names) == prev:
                no_new += 1
                if no_new >= 5:
                    break
            else:
                no_new = 0

        # Clear search
        search_input.click_input()
        time.sleep(0.2)
        # Select all and delete
        search_input.type_keys("^a{DELETE}")
        time.sleep(0.5)

        # Filter to only those containing 'sql'
        sql_names = [n for n in found_names.values() if matches_sql(n)]
        print(f"  After SQL filter: {len(sql_names)} contacts.")
        return sql_names

    except Exception as e:
        print(f"  ✗ Search failed: {e}. Falling back to scroll.")
        # Try to clear search
        try:
            search_input.click_input()
            time.sleep(0.2)
            search_input.type_keys("^a{DELETE}")
            time.sleep(0.3)
        except Exception:
            pass
        return []


def discover_contacts(dlg, db: ExporterDB, run_id: str,
                      method: str = "scroll") -> list[dict]:
    """
    Discover SQL contacts and persist them to the database.

    Args:
        dlg: Zalo window wrapper.
        db: Database instance.
        run_id: Current run ID.
        method: 'search', 'scroll', or 'both'.

    Returns:
        List of conversation dicts from the database.
    """
    print("\nDiscovering SQL contacts…")
    bring_zalo_to_front()

    names: list[str] = []

    if method in ("search", "both"):
        names = discover_by_search(dlg, db, run_id)
        if not names and method == "search":
            print("  Search found nothing. Try --discover-method scroll.")

    if method == "scroll" or (method == "both" and not names):
        scroll_names = discover_by_scroll(dlg, db, run_id)
        # Merge, preferring existing names
        existing_norms = {normalize_for_match(n) for n in names}
        for n in scroll_names:
            if normalize_for_match(n) not in existing_norms:
                names.append(n)

    if not names:
        print("  No SQL contacts found.")
        return []

    # Persist to database (detect duplicates by normalized name)
    conversations = []
    seen_norms: dict[str, str] = {}  # norm → first conv_id

    for name in sorted(names):
        norm = normalize_for_match(name)

        # Check if already exists in this run
        existing = db.find_conversation_by_name(run_id, norm)
        if existing:
            conversations.append(existing)
            continue

        # Check for ambiguous duplicates (different original names, same normalized)
        if norm in seen_norms:
            print(f"  ⚠ Duplicate normalized name '{norm}': '{name}' — creating separate entry.")

        conv_id = db.add_conversation(run_id, name, norm)
        seen_norms[norm] = conv_id
        conv = db.find_conversation_by_name(run_id, norm)
        if conv:
            conversations.append(conv)

    print(f"\n  Total: {len(conversations)} SQL contacts persisted.")
    for c in conversations:
        print(f"    • {c['display_name']} [{c['status']}]")

    return conversations
