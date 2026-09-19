#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Zalo SQL Exporter — extract chat history from Zalo PC.

Usage:
    python zalo_phase2.py                    # discover + extract (default)
    python zalo_phase2.py discover           # find SQL contacts
    python zalo_phase2.py extract            # extract/resume
    python zalo_phase2.py status             # show progress
    python zalo_phase2.py export             # generate CSV + JSON

Press F8 at any time to stop safely.
"""

from zalo_exporter.cli import main

if __name__ == "__main__":
    main()
