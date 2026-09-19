"""
Low-level Zalo PC window interaction.

Handles:
  - Finding and connecting to the Zalo window via pywinauto UIA.
  - Bringing Zalo to foreground via SetForegroundWindow.
  - Scrolling at screen coordinates via win32 mouse_event (avoids
    the virtual-coordinates bug with pywinauto's wheel_mouse_input).
  - F8 global stop hotkey via background thread.
  - Caching of resolved UIA wrapper objects.
"""

import time
import ctypes
import threading
from pywinauto import Desktop, Application

from . import config


# =====================================================================
#  Global state
# =====================================================================

_zalo_hwnd: int | None = None
_stop_event = threading.Event()


# =====================================================================
#  Stop hotkey (F8)
# =====================================================================

def is_stop_requested() -> bool:
    """Check whether the user pressed F8."""
    return _stop_event.is_set()


def request_stop():
    """Programmatically trigger stop (e.g. from signal handler)."""
    _stop_event.set()


def reset_stop():
    """Clear the stop flag (e.g. at start of a new command)."""
    _stop_event.clear()


def _hotkey_listener():
    """Background daemon thread polling for F8 key press."""
    while not _stop_event.is_set():
        # GetAsyncKeyState returns high bit set if key is currently pressed
        if ctypes.windll.user32.GetAsyncKeyState(config.VK_F8) & 0x8000:
            print("\n⚠  F8 pressed — stopping after current operation…")
            _stop_event.set()
            return
        time.sleep(config.HOTKEY_POLL_INTERVAL)


def start_hotkey_listener():
    """Start the F8 hotkey listener in a background thread."""
    reset_stop()
    t = threading.Thread(target=_hotkey_listener, daemon=True)
    t.start()


# =====================================================================
#  Zalo window management
# =====================================================================

def find_zalo_window():
    """
    Find and connect to the main Zalo PC window.

    Returns:
        The pywinauto top-window wrapper, or None if not found.
    """
    global _zalo_hwnd
    desktop = Desktop(backend="uia")
    for w in desktop.windows():
        title = w.window_text()
        if title and (title == "Zalo" or title.startswith("Zalo ")):
            _zalo_hwnd = w.handle
            app = Application(backend="uia").connect(handle=w.handle)
            return app.top_window()
    return None


def bring_zalo_to_front():
    """
    Bring the Zalo window to the foreground.

    Does nothing if stop has been requested (to let the user
    regain control of their desktop).
    """
    if is_stop_requested():
        return
    if _zalo_hwnd:
        ctypes.windll.user32.SetForegroundWindow(_zalo_hwnd)
        time.sleep(config.FOREGROUND_SETTLE)


def get_zalo_hwnd() -> int | None:
    return _zalo_hwnd


# =====================================================================
#  Screen-coordinate scrolling
# =====================================================================

def scroll_at(x: int, y: int, ticks: int, direction: str = "down"):
    """
    Send a mouse-wheel event at absolute screen coordinates (x, y).

    Args:
        x, y: Screen pixel coordinates.
        ticks: Number of wheel notches.
        direction: 'up' or 'down'.
    """
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(config.CURSOR_MOVE_SETTLE)
    MOUSEEVENTF_WHEEL = 0x0800
    delta = ticks * config.WHEEL_DELTA if direction == "up" else -(ticks * config.WHEEL_DELTA)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)


# =====================================================================
#  Coordinate helpers
# =====================================================================

def get_sidebar_center(dlg) -> tuple[int, int]:
    """Return (x, y) screen coordinates at the center of the sidebar."""
    r = dlg.rectangle()
    return r.left + 250, r.top + (r.bottom - r.top) // 2


def get_chat_center(dlg) -> tuple[int, int]:
    """Return (x, y) screen coordinates at the center of the chat area."""
    r = dlg.rectangle()
    chat_left = r.left + 510
    cx = chat_left + (r.right - chat_left) // 2
    cy = r.top + (r.bottom - r.top) // 2
    return cx, cy


# =====================================================================
#  UIA control helpers (with caching)
# =====================================================================

def resolve_control(dlg, auto_id: str, control_type: str, timeout: float = 3.0):
    """
    Find a child control by auto_id and control_type, returning
    the resolved wrapper object (not the lazy spec).

    Returns None if the control does not exist within *timeout* seconds.
    """
    spec = dlg.child_window(auto_id=auto_id, control_type=control_type)
    if spec.exists(timeout=timeout):
        return spec.wrapper_object()
    return None


def get_conversation_list(dlg):
    """Return wrapper for conversationList Table, prioritizing visible ones."""
    # 1. Try standard conversationList first
    try:
        elements = dlg.descendants(auto_id="conversationList", control_type="Table")
        for el in elements:
            if el.is_visible():
                return el
    except Exception:
        pass
        
    # 2. If in Labels (Phân loại) tab, auto_id might be different. 
    # Find any visible Table/List on the left sidebar.
    try:
        for c_type in ["Table", "List"]:
            for el in dlg.descendants(control_type=c_type):
                if el.is_visible():
                    rect = el.rectangle()
                    # Sidebar lists are typically positioned on the left side
                    if rect.left < 200 and rect.width() > 100 and rect.height() > 300:
                        return el
    except Exception:
        pass
        
    # Fallback
    return resolve_control(dlg, "conversationList", "Table", timeout=8.0)


def get_message_view(dlg):
    """Return cached wrapper for messageView Group."""
    return resolve_control(dlg, "messageView", "Group")


def get_chat_view_container(dlg):
    """Return cached wrapper for chatViewContainer Group."""
    return resolve_control(dlg, "chatViewContainer", "Group")


def get_search_input(dlg):
    """Return cached wrapper for the search box Edit."""
    return resolve_control(dlg, "contact-search-input", "Edit")


def read_open_conversation_name(dlg) -> str | None:
    """
    Read the name of the currently open conversation from
    chatViewContainer's first visible Text child.

    Returns the name string, or None if nothing is open.
    """
    container = get_chat_view_container(dlg)
    if not container:
        return None
    try:
        for child in container.children(control_type="Text"):
            text = child.window_text()
            if not text:
                continue
            rect = child.rectangle()
            # The header name is the first visible text element
            # (PUA icons have empty or PUA-only text)
            from .name_matching import is_pua_only
            if rect.width() > 0 and not is_pua_only(text):
                return text
    except Exception:
        pass
    return None
