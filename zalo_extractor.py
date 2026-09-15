import time
import json
import csv
import codecs
from pywinauto import Application

def get_sender_from_x(x_coord, chat_center_x):
    # If the message is on the right side of the chat view, it's from "Me"
    if x_coord > chat_center_x:
        return "Me"
    else:
        return "Other"

def extract_zalo():
    print("Connecting to Zalo...")
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        windows = desktop.windows()
        zalo_win = None
        for w in windows:
            title = w.window_text()
            if title and "Zalo" in title and "Visual Studio" not in title and "Code" not in title and "PowerShell" not in title:
                zalo_win = w
                break
                
        if not zalo_win:
            print("Cannot find Zalo window. Please make sure Zalo PC is running.")
            return
            
        app = Application(backend="uia").connect(handle=zalo_win.handle)
        dlg = app.top_window()
    except Exception as e:
        print(f"Cannot find or connect to Zalo: {e}")
        return

    try:
        # Find the message view
        msg_view = dlg.child_window(auto_id="messageView", control_type="Group")
        if not msg_view.exists(timeout=2):
            print("Cannot find 'messageView'. Please make sure a conversation is open.")
            return
    except Exception as e:
        print(f"Error locating message view: {e}")
        return

    msg_view_rect = msg_view.rectangle()
    chat_center_x = msg_view_rect.left + (msg_view_rect.width() / 2)
    print(f"Chat View Box: {msg_view_rect}, Center X: {chat_center_x}")

    all_messages = []
    seen_texts = set()
    capture_order = 0
    max_scrolls = 3
    
    # We will try to guess conversation name from the title or header later.
    # For now, just use a placeholder since Zalo UI can be tricky without exact selectors.
    conversation_name = "Unknown_Conversation"
    
    print("Starting extraction (Phase 1)...")
    
    for scroll_idx in range(max_scrolls + 1):
        print(f"--- Capture Step {scroll_idx + 1}/{max_scrolls + 1} ---")
        
        # Collect visible static texts in messageView
        children = msg_view.children(control_type="Text")
        
        step_messages = []
        for child in children:
            rect = child.rectangle()
            # If width == 0 or left == 0, it's likely virtualized/off-screen
            if rect.width() > 0 and rect.left > 0:
                text = child.window_text()
                if not text or text.strip() == "":
                    continue
                    
                # A simple heuristic to filter out timestamps vs messages
                # Actually, user wants raw data. We just record everything visible.
                # In Zalo, emojis are sometimes single characters.
                sender = get_sender_from_x(rect.left, chat_center_x)
                
                # Check for duplicates (very basic deduplication based on text and sender)
                # Note: In a real scenario, we need better deduplication because texts can repeat.
                # User instructed: "Không xóa nhầm các tin hợp lệ có cùng nội dung. 
                # Chỉ loại phần chồng lặp giữa các lần cuộn khi đủ bằng chứng"
                # For Phase 1, we just collect everything, and we'll do a simple dedup based on order if needed,
                # but to be safe we just append and mark it.
                
                msg_data = {
                    "capture_order": capture_order,
                    "conversation_name": conversation_name,
                    "sender": sender,
                    "timestamp_raw": None, # Hard to reliably link timestamp to message in flat UI without complex heuristics
                    "text": text,
                    "message_type": "text",
                    "rect_left": rect.left,
                    "rect_top": rect.top
                }
                step_messages.append(msg_data)
                capture_order += 1
                
        print(f"Captured {len(step_messages)} visible text elements in this step.")
        all_messages.extend(step_messages)
        
        if scroll_idx < max_scrolls:
            print("Scrolling up...")
            try:
                # Try to scroll up using Wheel
                msg_view.set_focus()
                # Wheel up
                msg_view.wheel_mouse_input(wheel_dist=3)
                time.sleep(1.5) # wait for virtualization to load
            except Exception as e:
                print(f"Scroll failed: {e}. Trying PageUp...")
                msg_view.type_keys("{PGUP}")
                time.sleep(1.5)

    print(f"\nExtraction finished. Total elements captured: {len(all_messages)}")
    
    # Save to JSON
    with codecs.open("zalo_extracted.json", "w", encoding="utf-8") as f:
        json.dump(all_messages, f, ensure_ascii=False, indent=4)
        
    # Save to CSV (UTF-8 BOM for Excel)
    with codecs.open("zalo_extracted.csv", "w", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["capture_order", "conversation_name", "sender", "timestamp_raw", "text", "message_type", "rect_left", "rect_top"])
        writer.writeheader()
        for m in all_messages:
            writer.writerow(m)
            
    print("Saved to zalo_extracted.json and zalo_extracted.csv")
    print("Check the results to see if the message text and sender side (Me vs Other) are correct.")

if __name__ == "__main__":
    extract_zalo()
