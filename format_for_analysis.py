"""
Transform raw Zalo CSV/JSON export into a clean, analysis-ready CSV.

Output: one row per real message, with date and time propagated from
nearby date/time markers onto each message row. Filters out UI noise,
date markers, time markers, and duplicates.

Usage:
    python format_for_analysis.py
    python format_for_analysis.py --input zalo_all_sql_history.csv --output zalo_clean.csv
"""

import csv
import codecs
import re
import argparse
import unicodedata
from collections import defaultdict


# ── helpers ──────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize NBSP and whitespace in display names."""
    if not name:
        return ""
    name = name.replace('\xa0', ' ')
    name = unicodedata.normalize('NFC', name)
    return re.sub(r'\s+', ' ', name).strip()


def map_sender(sender: str) -> str:
    s = sender.strip().lower()
    if s == 'me':
        return 'Tôi'
    elif s == 'other':
        return 'Đối phương'
    return sender


_DATE_LONG = re.compile(r'^(\d{1,2})/(\d{1,2})/(\d{4})$')
_DATE_SHORT = re.compile(r'^(\d{1,2})/(\d{1,2})/(\d{2})$')
_TIME_ONLY = re.compile(r'^(\d{1,2}):(\d{2})$')
_DATETIME = re.compile(r'^(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})/(\d{4})$')

# UI noise that should be excluded from the clean output
_NOISE = {
    "message", "chưa có tin nhắn nào", "tin nhắn mới", "bạn đã tham gia",
    "+1 pin", "photo", "sticker", "gif", "photo unavailable", "video",
    "file", "name card", "location", "audio", "link",
}

# Zalo emoticon codes
_REACTION_RE = re.compile(r'^[:/;][\-\w]+$')
_REACTION_LITERALS = {':>', ':o', ':-((', ':-h', '/-strong', '/-heart'}


def parse_date(text: str) -> str | None:
    """Parse DD/MM/YYYY or DD/MM/YY -> YYYY-MM-DD, or return None."""
    m = _DATE_LONG.match(text.strip())
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = _DATE_SHORT.match(text.strip())
    if m:
        year = int(m.group(3))
        full_year = 2000 + year if year < 100 else year
        return f"{full_year}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return None


def parse_time(text: str) -> str | None:
    """Parse HH:MM -> HH:MM, or None."""
    m = _TIME_ONLY.match(text.strip())
    if m:
        return f"{m.group(1).zfill(2)}:{m.group(2)}"
    return None


def parse_datetime(text: str) -> tuple[str, str] | None:
    """Parse 'HH:MM DD/MM/YYYY' -> (YYYY-MM-DD, HH:MM) or None."""
    m = _DATETIME.match(text.strip())
    if m:
        date = f"{m.group(5)}-{m.group(4).zfill(2)}-{m.group(3).zfill(2)}"
        time = f"{m.group(1).zfill(2)}:{m.group(2)}"
        return date, time
    return None


def classify(text: str, elem_type: str) -> str:
    """Classify a row as 'date', 'time', 'datetime', 'noise', 'reaction', or 'message'."""
    if elem_type == 'date':
        return 'date'
    if elem_type == 'time':
        return 'time'
    if elem_type == 'datetime':
        return 'datetime'

    t = text.strip().lower()
    if t in _NOISE:
        return 'noise'
    if _REACTION_RE.match(text.strip()) or text.strip() in _REACTION_LITERALS:
        return 'reaction'
    # Auto-detect inline date/time even if element_type is 'text'
    if parse_date(text) is not None:
        return 'date'
    if parse_time(text) is not None:
        return 'time'
    if parse_datetime(text) is not None:
        return 'datetime'
    return 'message'


# ── main transform ──────────────────────────────────────────────────

def transform(input_path: str, output_path: str):
    print(f"Reading {input_path}...")
    with codecs.open(input_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"  -> {len(rows)} raw rows loaded.")

    # Group by conversation
    convs: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        name = normalize_name(r.get('display_name', ''))
        convs[name].append(r)

    out_rows = []
    stats = {'total_in': 0, 'messages': 0, 'skipped_noise': 0,
             'skipped_date': 0, 'skipped_time': 0, 'skipped_dup': 0,
             'reactions': 0}

    for conv_name in sorted(convs.keys()):
        items = convs[conv_name]
        # Sort oldest -> newest: highest batch first, then position ascending
        items.sort(key=lambda x: (-int(x.get('batch_number', 0)),
                                   int(x.get('position_in_batch', 0))))

        current_date = ""
        current_time = ""

        for item in items:
            stats['total_in'] += 1
            text = item.get('text_content', '')
            elem_type = item.get('element_type', '')
            is_dup = int(item.get('is_duplicate', 0))

            cat = classify(text, elem_type)

            # Update running date/time from markers
            if cat == 'date':
                d = parse_date(text)
                if d:
                    current_date = d
                current_time = ""  # reset time on new date
                stats['skipped_date'] += 1
                continue

            if cat == 'time':
                t = parse_time(text)
                if t:
                    current_time = t
                stats['skipped_time'] += 1
                continue

            if cat == 'datetime':
                dt = parse_datetime(text)
                if dt:
                    current_date, current_time = dt
                stats['skipped_time'] += 1
                continue

            if cat == 'noise':
                stats['skipped_noise'] += 1
                continue

            if is_dup:
                stats['skipped_dup'] += 1
                continue

            # It's a real message or reaction
            sender = map_sender(item.get('sender', ''))

            if cat == 'reaction':
                stats['reactions'] += 1
                continue  # filter out reactions entirely
            else:
                stats['messages'] += 1
                record_type = 'message'

            out_rows.append({
                'conversation_name': conv_name,
                'message_date': current_date,
                'message_time': current_time,
                'sender': sender,
                'content': text,
                'record_type': record_type,
            })

            # Reset time after attaching it to a message
            # (each time marker applies to the immediately following message)
            current_time = ""

    # Deduplicate overlapping blocks caused by scroll-overlap between batches.
    # Two-pass approach:
    #   Pass 1: Remove block overlaps (consecutive repeated sequences)
    #   Pass 2: Remove near-duplicate messages (same sender+content within
    #           a sliding window — catches non-adjacent duplicates from
    #           batch boundary artifacts)
    MAX_BLOCK = 40   # max viewport overlap size to check
    WINDOW = 60      # lookback window for near-duplicate detection

    def _dedup_conversation(msgs):
        """Remove duplicate blocks within a single conversation's messages."""
        if len(msgs) <= 1:
            return msgs, 0

        # Pass 1: block overlap removal
        pass1 = []
        i = 0
        n = len(msgs)
        removed = 0
        while i < n:
            best_block = 0
            if len(pass1) >= 1:
                max_check = min(MAX_BLOCK, len(pass1), n - i)
                for block_size in range(max_check, 0, -1):
                    match = True
                    for j in range(block_size):
                        r = pass1[-(block_size - j)]
                        m = msgs[i + j]
                        if r['sender'] != m['sender'] or r['content'] != m['content']:
                            match = False
                            break
                    if match:
                        best_block = block_size
                        break
            if best_block > 0:
                i += best_block
                removed += best_block
            else:
                pass1.append(msgs[i])
                i += 1

        # Pass 2: sliding-window near-duplicate removal
        # If (sender, content) was already seen in the last WINDOW messages,
        # it's almost certainly a scroll artifact — skip it.
        # Exception: very short messages (<=3 chars) like "ok", "dạ" can
        # legitimately repeat, so we only dedup those if consecutive.
        result = []
        for row in pass1:
            key = (row['sender'], row['content'])
            is_short = len(row['content'].strip()) <= 3

            if is_short:
                # For short messages, only remove if consecutive duplicate
                if result and result[-1]['sender'] == row['sender'] and result[-1]['content'] == row['content']:
                    removed += 1
                    continue
            else:
                # For longer messages, check sliding window
                window_start = max(0, len(result) - WINDOW)
                found = False
                for prev in result[window_start:]:
                    if prev['sender'] == row['sender'] and prev['content'] == row['content']:
                        found = True
                        break
                if found:
                    removed += 1
                    continue

            result.append(row)

        return result, removed

    # Group out_rows by conversation, dedup each, then reassemble
    from itertools import groupby
    deduped = []
    for conv_name, group in groupby(out_rows, key=lambda r: r['conversation_name']):
        cleaned, removed = _dedup_conversation(list(group))
        deduped.extend(cleaned)
        stats['skipped_dup'] += removed

    # Write
    fields = ['conversation_name', 'message_date', 'message_time',
              'sender', 'content', 'record_type']

    print(f"Writing {output_path}...")
    with codecs.open(output_path, 'w', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(deduped)

    print(f"\n{'='*50}")
    print(f"  Input rows:       {stats['total_in']:>8,}")
    print(f"  Output rows:      {len(deduped):>8,}")
    print(f"    Messages:       {stats['messages']:>8,}")
    print(f"    Reactions:      {stats['reactions']:>8,}")
    print(f"  Filtered out:")
    print(f"    Date markers:   {stats['skipped_date']:>8,}")
    print(f"    Time markers:   {stats['skipped_time']:>8,}")
    print(f"    UI noise:       {stats['skipped_noise']:>8,}")
    print(f"    Duplicates:     {stats['skipped_dup']:>8,}")
    print(f"  Conversations:    {len(convs):>8,}")
    print(f"{'='*50}")
    print("Done!")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Transform raw Zalo export into a clean, analysis-ready CSV.")
    parser.add_argument("--input", default="zalo_all_sql_history.csv",
                        help="Input CSV file (default: zalo_all_sql_history.csv)")
    parser.add_argument("--output", default="zalo_clean.csv",
                        help="Output CSV file (default: zalo_clean.csv)")
    args = parser.parse_args()
    transform(args.input, args.output)
