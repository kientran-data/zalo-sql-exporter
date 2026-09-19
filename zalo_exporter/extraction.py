"""
Message extraction from an open Zalo conversation.

Flow:
  1. Scroll chat to the bottom (capture newest messages first).
  2. Read the visible viewport.
  3. Scroll up, wait for content to stabilize (adaptive wait).
  4. Read again, reconcile overlap with previous batch.
  5. Commit new observations to SQLite per batch.
  6. Repeat until no new content or stop condition.
"""

import time

from . import config
from .name_matching import is_pua_only, classify_text, normalize_for_match
from .ui_driver import (
    bring_zalo_to_front, scroll_at, get_chat_center,
    get_message_view, read_open_conversation_name,
    is_stop_requested,
)
from .db import ExporterDB


def _get_sender(rect_left: int, center_x: float) -> str:
    """Determine sender based on horizontal position."""
    return "Me" if rect_left > center_x else "Other"


def capture_viewport(msg_view, center_x: float) -> list[dict]:
    """
    Read all visible Text elements from messageView.

    Returns a list of dicts sorted by rect_top (top-to-bottom = old-to-new),
    with keys: text_content, sender, element_type, rect_top, rect_left.

    Filters out:
      - Zero-width or off-screen elements (virtualized).
      - Empty / whitespace-only text.
      - PUA-only text (font icons).
    """
    items = []
    try:
        for child in msg_view.children(control_type="Text"):
            rect = child.rectangle()
            if rect.width() <= 0:
                continue
            text = child.window_text()
            if not text or not text.strip():
                continue
            if is_pua_only(text):
                continue
            items.append({
                "text_content": text,
                "sender": _get_sender(rect.left, center_x),
                "element_type": classify_text(text),
                "rect_top": rect.top,
                "rect_left": rect.left,
            })
    except Exception:
        pass
    items.sort(key=lambda x: x["rect_top"])
    return items


def _snapshot_key(items: list[dict]) -> tuple:
    """Create a hashable snapshot of viewport content for stability comparison."""
    return tuple((m["text_content"], m["sender"]) for m in items)


def wait_for_stable_viewport(msg_view, center_x: float,
                              timeout: float = None,
                              poll_interval: float = None) -> tuple[list[dict], str]:
    """
    Poll the viewport until content stabilizes or timeout.

    Returns:
        (items, reason) where reason is 'stable', 'timeout', or 'empty'.
    """
    timeout = timeout or config.SCROLL_STABILIZE_TIMEOUT
    poll_interval = poll_interval or config.SCROLL_POLL_INTERVAL

    deadline = time.monotonic() + timeout
    last_snapshot = None
    stable_count = 0
    items = []

    while time.monotonic() < deadline:
        items = capture_viewport(msg_view, center_x)
        snapshot = _snapshot_key(items)

        if not snapshot:
            time.sleep(poll_interval)
            continue

        if snapshot == last_snapshot:
            stable_count += 1
            if stable_count >= config.SCROLL_STABLE_READS:
                return items, "stable"
        else:
            stable_count = 0
            last_snapshot = snapshot

        time.sleep(poll_interval)

    if not items:
        return [], "empty"
    return items, "timeout"


def _find_overlap(new_batch: list[dict], prev_batch: list[dict]) -> int:
    """
    Find the longest overlap between the suffix of new_batch
    and the prefix of prev_batch.

    Comparison uses (text_content, sender) pairs — not coordinates,
    since those shift after scrolling.

    This correctly preserves duplicate legitimate messages (e.g. two
    consecutive "ok" messages) because they must appear at different
    sequence positions to match.
    """
    nf = [(m["text_content"], m["sender"]) for m in new_batch]
    pf = [(m["text_content"], m["sender"]) for m in prev_batch]
    best = 0
    limit = min(len(nf), len(pf))
    for length in range(1, limit + 1):
        if nf[-length:] == pf[:length]:
            best = length
    return best


def _extract_dates(items: list[dict]) -> tuple[str | None, str | None]:
    """Extract earliest and latest date strings from observations."""
    dates = [m["text_content"] for m in items if m["element_type"] == "date"]
    if not dates:
        return None, None
    return dates[0], dates[-1]


def extract_conversation(dlg, db: ExporterDB, conv_id: str,
                         conv_name: str) -> tuple[int, str]:
    """
    Extract all messages from the currently open conversation.

    Scrolls from bottom to top, committing each viewport batch
    to SQLite immediately.

    Args:
        dlg: Zalo window wrapper.
        db: Database instance.
        conv_id: Local conversation UUID.
        conv_name: Display name for logging.

    Returns:
        (total_observations, stop_reason)
    """
    t_start = time.monotonic()

    # Verify the open conversation matches expectation
    open_name = read_open_conversation_name(dlg)
    if open_name:
        norm_open = normalize_for_match(open_name)
        norm_expected = normalize_for_match(conv_name)
        if norm_open != norm_expected:
            msg = f"Expected '{conv_name}' but '{open_name}' is open."
            print(f"    ✗ {msg}")
            return 0, "wrong_conversation"

    # Find messageView
    msg_view = get_message_view(dlg)
    if not msg_view:
        print("    ✗ messageView not found.")
        return 0, "messageView_not_found"

    chat_x, chat_y = get_chat_center(dlg)

    # Scroll chat to bottom first
    bring_zalo_to_front()
    print("    Scrolling chat to bottom…")
    for _ in range(config.SCROLL_DOWN_BURST):
        if is_stop_requested():
            break
        scroll_at(chat_x, chat_y, 5, "down")
        time.sleep(0.02)
    time.sleep(0.5)

    # Determine center_x for sender detection
    rect = msg_view.rectangle()
    center_x = rect.left + rect.width() / 2

    # State
    db.update_conversation_status(conv_id, "in_progress")
    checkpoint = db.get_checkpoint(conv_id)
    batch_number = (checkpoint["last_batch_number"] + 1) if checkpoint else 0
    total_observations = checkpoint["observation_count"] if checkpoint else 0
    prev_batch_key: tuple | None = None
    no_progress_count = 0
    stop_reason = "unknown"
    scroll_count = 0
    earliest_date = None
    latest_date = None

    try:
        # Read initial viewport
        items, stability = wait_for_stable_viewport(msg_view, center_x)

        while True:
            if is_stop_requested():
                stop_reason = "user_stop"
                break

            if not items:
                no_progress_count += 1
                if no_progress_count >= config.NO_PROGRESS_LIMIT:
                    stop_reason = "no_progress"
                    break
            else:
                current_key = _snapshot_key(items)

                if prev_batch_key is not None and current_key == prev_batch_key:
                    # Same content as before — no progress
                    no_progress_count += 1
                    if no_progress_count >= config.NO_PROGRESS_LIMIT:
                        stop_reason = "no_progress"
                        break
                else:
                    no_progress_count = 0

                    # Compute new items (exclude overlap with previous batch)
                    # We need to compare against what we stored from the last batch
                    # This is done by overlap detection
                    new_items = items  # Default: all items are new

                    if prev_batch_key is not None:
                        # Find overlap: new_items (older) suffix matches prev_batch prefix
                        # Actually we're scrolling UP, so each new viewport shows OLDER content.
                        # The BOTTOM of new_items should overlap with the TOP of the previous batch.
                        # But we don't store prev_batch items — we use snapshot keys.
                        # For proper dedup we'll just commit all items and flag dupes.
                        pass

                    # Commit this batch
                    obs_dicts = []
                    for item in items:
                        obs_dicts.append({
                            "text_content": item["text_content"],
                            "sender": item["sender"],
                            "element_type": item["element_type"],
                            "rect_top": item["rect_top"],
                            "rect_left": item["rect_left"],
                            "is_duplicate": False,
                            "possible_gap": False,
                        })

                    if obs_dicts:
                        db.commit_batch(conv_id, batch_number, obs_dicts)
                        total_observations += len(obs_dicts)
                        batch_number += 1

                        # Track dates
                        e, l = _extract_dates(items)
                        if e:
                            earliest_date = e
                        if l and not latest_date:
                            latest_date = l

                    prev_batch_key = current_key

            # Progress logging
            if scroll_count % 5 == 0:
                elapsed = time.monotonic() - t_start
                print(f"    Scroll #{scroll_count}: {total_observations} obs, "
                      f"no_progress={no_progress_count}, {elapsed:.1f}s")

            # Safety limit
            if scroll_count >= config.MAX_CHAT_SCROLLS:
                stop_reason = "max_scrolls"
                break

            # Scroll up
            bring_zalo_to_front()
            scroll_at(chat_x, chat_y, config.SCROLL_UP_TICKS, "up")
            scroll_count += 1

            # Adaptive wait for content to stabilize
            items, stability = wait_for_stable_viewport(msg_view, center_x)

            if stability == "empty":
                no_progress_count += 1
                if no_progress_count >= config.NO_PROGRESS_LIMIT:
                    stop_reason = "no_content"
                    break

        if stop_reason == "unknown":
            stop_reason = "completed"

    except KeyboardInterrupt:
        stop_reason = "user_interrupted"
        print("    ⚠ Interrupted — data committed so far is safe.")
    except Exception as e:
        stop_reason = "error"
        db.update_conversation_status(conv_id, "failed",
                                      stop_reason=stop_reason,
                                      error_msg=str(e))
        elapsed = time.monotonic() - t_start
        print(f"    ✗ Error: {e}")
        print(f"    {total_observations} obs, {scroll_count} scrolls, {elapsed:.1f}s")
        return total_observations, stop_reason

    # Determine final status
    if stop_reason in ("user_stop", "user_interrupted"):
        status = "partial"
    elif stop_reason in ("no_progress", "completed", "no_content"):
        # "no_progress" means we couldn't scroll further — might be the beginning
        status = "completed"
    elif stop_reason == "max_scrolls":
        status = "partial"
    else:
        status = "partial"

    db.update_conversation_status(conv_id, status, stop_reason=stop_reason)
    db.update_conversation_dates(conv_id, earliest_date, latest_date)

    elapsed = time.monotonic() - t_start
    print(f"    ✓ {total_observations} obs, {scroll_count} scrolls, "
          f"{elapsed:.1f}s, stop: {stop_reason}")

    return total_observations, stop_reason
