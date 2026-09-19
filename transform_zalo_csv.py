import csv
import argparse
import codecs
import re
from collections import defaultdict

def parse_args():
    parser = argparse.ArgumentParser(description="Transform Zalo CSV export to a cleaner format.")
    parser.add_argument("--input", required=True, help="Input CSV file")
    parser.add_argument("--output", required=True, help="Output CSV file")
    return parser.parse_args()

def normalize_name(name):
    if not name:
        return ""
    # Replace non-breaking spaces and normalize, also clean up the  character if present
    return name.replace('\xa0', ' ').replace('', ' ').strip()

def map_sender(sender):
    if sender.lower() == 'me':
        return 'Tôi'
    elif sender.lower() == 'other':
        return 'Đối phương'
    return sender

def classify_record(text, elem_type):
    if elem_type == 'date':
        return 'date_marker'
    if elem_type == 'time':
        return 'time_marker'
    
    text_lower = text.lower().strip()
    noise_patterns = [
        "message", "chưa có tin nhắn nào", "tin nhắn mới", "bạn đã tham gia",
        "+1 pin", "photo", "sticker", "gif", "photo unavailable", "video", "file"
    ]
    if any(p == text_lower for p in noise_patterns):
        return 'possible_ui_noise'
    
    # Check for Zalo reactions (often start with /-, :-, etc)
    if re.match(r'^[:/;][\-\w]+$', text) or text in [':>', ':o', ':-((', ':-h', '/-strong', '/-heart']:
        return 'reaction'
        
    return 'message'

def format_date(d_str):
    # Expect DD/MM/YYYY, convert to YYYY-MM-DD
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', d_str)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # Expect YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', d_str):
        return d_str
    return d_str

def format_time(t_str):
    # Expect HH:MM or HH:MM:SS
    m = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$', t_str)
    if m:
        h = m.group(1).zfill(2)
        m_min = m.group(2)
        s = m.group(3) if m.group(3) else "00"
        # We can just return HH:MM if that's what was provided
        if not m.group(3):
            return f"{h}:{m_min}"
        return f"{h}:{m_min}:{s}"
    return t_str

def process_csv(input_file, output_file):
    print(f"Reading input from {input_file}...")
    try:
        with codecs.open(input_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print(f"Error: {input_file} not found.")
        return

    # Group by conversation
    convs = defaultdict(list)
    for r in rows:
        conv_name = normalize_name(r.get('display_name', ''))
        convs[conv_name].append(r)
        
    out_rows = []
    
    print("Transforming records...")
    
    for conv_name, items in convs.items():
        # Sort oldest to newest: batch_number DESC, position_in_batch ASC
        items.sort(key=lambda x: (-int(x.get('batch_number', 0)), int(x.get('position_in_batch', 0))))
        
        current_date = ""
        
        for item in items:
            elem_type = item.get('element_type', '')
            text = item.get('text_content', '')
            sender = map_sender(item.get('sender', ''))
            
            rec_type = classify_record(text, elem_type)
            
            msg_date = current_date
            msg_time = ""
            
            if rec_type == 'date_marker':
                current_date = format_date(text)
                msg_date = current_date
                
            if rec_type == 'time_marker':
                msg_time = format_time(text)
                
            review_note = []
            
            if int(item.get('is_duplicate', 0)) == 1:
                review_note.append("Suspected scroll-overlap duplicate")
            if int(item.get('possible_gap', 0)) == 1:
                review_note.append("Possible gap before this message")
                
            # As per rules: Leave unknown dates/times blank.
            # We track current_date because a date marker applies to all messages below it.
            # We do NOT track current_time for subsequent messages because time markers typically 
            # apply only to a specific adjacent message cluster in UIA.
            if rec_type in ('message', 'possible_ui_noise', 'reaction'):
                if msg_date:
                    pass # Keep the inferred date
                else:
                    review_note.append("Date unknown")
                    
            out_rows.append({
                'conversation_name': conv_name,
                'message_date': msg_date,
                'message_time': msg_time,
                'sender': sender,
                'content': text,
                'record_type': rec_type,
                'review_note': " | ".join(review_note),
                'source_obs_ids': item.get('obs_id', '')
            })
            
    # Write output
    print(f"Writing output to {output_file}...")
    fields = [
        'conversation_name', 'message_date', 'message_time', 'sender',
        'content', 'record_type', 'review_note', 'source_obs_ids'
    ]
    with codecs.open(output_file, 'w', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
        
    print(f"Successfully processed {len(rows)} input rows into {len(out_rows)} output rows.")
    print("Limitations/Notes:")
    print(" - Time is only attached to time_marker rows; messages have blank time to avoid false associations.")
    print(" - Duplicate records were kept for manual filtering.")
    print(" - Oldest-to-newest order reconstructed using batch numbers.")
    print("Done.")

if __name__ == '__main__':
    args = parse_args()
    process_csv(args.input, args.output)
