"""
Configuration constants for Zalo SQL Exporter.
"""

import os

# ----- Extraction tuning -----
MAX_CHAT_SCROLLS = 500          # Safety limit per conversation
SCROLL_STABILIZE_TIMEOUT = 1.5  # Max seconds to wait for viewport to stabilize after scroll
SCROLL_POLL_INTERVAL = 0.06     # Seconds between stability polls
SCROLL_STABLE_READS = 2         # Consecutive identical reads = stable
NO_PROGRESS_LIMIT = 10          # Stop after N scrolls with zero new observations
SCROLL_DOWN_BURST = 30          # Number of wheel ticks to scroll to bottom of chat
SCROLL_UP_TICKS = 3             # Wheel ticks per upward scroll step

# ----- Sidebar discovery -----
SIDEBAR_MAX_SCROLLS = 500       # Safety limit for sidebar scanning
SIDEBAR_NO_NEW_LIMIT = 30       # Stop sidebar scan after N scrolls with no new SQL contact
SIDEBAR_SCROLL_TICKS = 3        # Wheel ticks per sidebar scroll step
SEARCH_RESULT_WAIT = 2.0        # Seconds to wait for search results after typing

# ----- Output files -----
DB_FILE = "zalo_exporter.db"
OUTPUT_CSV = "zalo_all_sql_history.csv"
OUTPUT_JSON = "zalo_all_sql_history.json"

# ----- UI interaction -----
WHEEL_DELTA = 120               # Windows wheel delta per tick
FOREGROUND_SETTLE = 0.08        # Seconds to wait after SetForegroundWindow
CLICK_SETTLE = 1.5              # Seconds to wait after clicking a contact
CURSOR_MOVE_SETTLE = 0.02       # Seconds to wait after moving cursor

# ----- Stop hotkey -----
VK_F8 = 0x77                    # Virtual key code for F8
HOTKEY_POLL_INTERVAL = 0.1      # Seconds between hotkey polls
