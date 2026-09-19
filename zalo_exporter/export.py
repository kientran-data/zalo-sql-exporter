"""
Export data from SQLite to CSV and JSON.

Always exports ALL data across all runs to prevent data loss
when the user re-runs the script.
"""

import csv
import json
import codecs

from . import config
from .db import ExporterDB


def export_csv(db: ExporterDB, run_id: str | None = None, output_path: str | None = None):
    """
    Export observations to CSV (UTF-8 BOM for Excel).

    Exports ALL runs' data to prevent data loss on re-run.
    """
    path = output_path or config.OUTPUT_CSV
    rows = db.get_all_observations_all_runs(exclude_duplicates=True)

    if not rows:
        print(f"  No observations to export.")
        return

    fields = [
        "obs_id", "display_name", "batch_number", "position_in_batch",
        "text_content", "sender", "element_type",
        "is_duplicate", "possible_gap", "captured_at",
    ]

    with codecs.open(path, "w", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})

    print(f"  [OK] CSV exported: {path} ({len(rows)} rows)")


def export_json(db: ExporterDB, run_id: str | None = None, output_path: str | None = None):
    """
    Export observations to JSON.

    Exports ALL runs' data to prevent data loss on re-run.
    """
    path = output_path or config.OUTPUT_JSON
    rows = db.get_all_observations_all_runs(exclude_duplicates=True)

    if not rows:
        print(f"  No observations to export.")
        return

    # Clean up internal fields
    clean = []
    for row in rows:
        entry = {
            "conversation": row.get("display_name"),
            "text": row.get("text_content"),
            "sender": row.get("sender"),
            "type": row.get("element_type"),
            "batch": row.get("batch_number"),
            "position": row.get("position_in_batch"),
            "possible_gap": bool(row.get("possible_gap")),
            "captured_at": row.get("captured_at"),
        }
        clean.append(entry)

    with codecs.open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)

    print(f"  [OK] JSON exported: {path} ({len(clean)} entries)")
