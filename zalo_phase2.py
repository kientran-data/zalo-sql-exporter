#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Zalo SQL Exporter - Phase 2
Tự động tìm tất cả liên hệ có biệt danh chứa "sql" trong sidebar,
click mở từng cuộc trò chuyện, cuộn lên để lấy toàn bộ lịch sử,
khử trùng lặp và xuất CSV + JSON.

Cách dùng:
    python zalo_phase2.py

Dừng khẩn cấp: Ctrl+C (script sẽ lưu dữ liệu đã thu thập trước khi dừng)
"""

import time
import json
import csv
import codecs
import re
import sys
from datetime import datetime
from pywinauto import Desktop, Application


# ===== CẤU HÌNH =====
MAX_CHAT_SCROLLS = 200       # Giới hạn số lần cuộn tối đa cho mỗi cuộc trò chuyện
SCROLL_WAIT_SEC = 1.5        # Thời gian chờ giữa các lần cuộn chat (giây)
SIDEBAR_SCROLL_PASSES = 500  # Số lần cuộn sidebar xuống để tìm thêm liên hệ SQL (đủ lớn để quét hết)
EMPTY_SCROLL_LIMIT = 3       # Dừng cuộn chat nếu N lần liên tiếp không có tin mới
OUTPUT_CSV = "zalo_all_sql_history.csv"
OUTPUT_JSON = "zalo_all_sql_history.json"
REPORT_FILE = "zalo_run_report.txt"


# ===== TIỆN ÍCH =====

def is_pua_only(text):
    """Kiểm tra text chỉ toàn ký tự Private Use Area (biểu tượng font icon Zalo)."""
    return all(0xE000 <= ord(c) <= 0xF8FF or c.isspace() for c in text)


def classify_element(text):
    """Phân loại thành phần text dựa trên pattern."""
    t = text.strip()
    if re.fullmatch(r'\d{2}/\d{2}/\d{4}', t):
        return "date"
    if re.fullmatch(r'\d{2}:\d{2}', t):
        return "time"
    if re.fullmatch(r'\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4}', t):
        return "datetime"
    return "text"


def get_sender(rect_left, center_x):
    """Xác định người gửi dựa trên vị trí ngang so với tâm khung chat."""
    return "Me" if rect_left > center_x else "Other"


# ===== TÌM CỬA SỔ ZALO =====

def find_zalo_window():
    """Tìm và kết nối tới cửa sổ Zalo PC chính."""
    desktop = Desktop(backend="uia")
    for w in desktop.windows():
        title = w.window_text()
        # Khớp chính xác "Zalo" để tránh nhầm VS Code, PowerShell...
        if title == "Zalo":
            app = Application(backend="uia").connect(handle=w.handle)
            return app.top_window()
    return None


# ===== KHÁM PHÁ LIÊN HỆ SQL =====

def discover_sql_contacts(dlg):
    """
    Tìm tất cả liên hệ có 'sql' (không phân biệt hoa/thường) trong tên
    từ danh sách hội thoại, bao gồm cả cuộn sidebar để tìm thêm.
    """
    print("Đang quét danh sách hội thoại tìm liên hệ SQL...")

    conv_list = dlg.child_window(auto_id="conversationList", control_type="Table")
    if not conv_list.exists(timeout=3):
        print("  Không tìm thấy danh sách hội thoại (conversationList).")
        return []

    sql_names = set()

    def scan_children():
        """Đọc tất cả children text của conversationList và lọc tên chứa 'sql'."""
        for child in conv_list.children(control_type="Text"):
            text = child.window_text()
            if text and "sql" in text.lower() and not is_pua_only(text):
                sql_names.add(text)

    # Bước 1: Cuộn sidebar LÊN ĐẦU trước (đảm bảo bắt đầu từ vị trí đầu tiên)
    try:
        conv_container = dlg.child_window(auto_id="conversationListId", control_type="Group")
        print("  Cuộn sidebar về đầu danh sách...")
        conv_container.set_focus()
        for _ in range(200):
            conv_container.wheel_mouse_input(wheel_dist=10)
            time.sleep(0.02)
        time.sleep(1)
    except Exception as e:
        print(f"  Lỗi khi cuộn sidebar: {e}")
        return []

    # Bước 2: Quét tại vị trí đầu
    scan_children()
    print(f"  Tìm thấy {len(sql_names)} liên hệ SQL từ đầu danh sách.")

    # Bước 3: Cuộn sidebar XUỐNG TẬN CÙNG, quét mỗi 3 lần cuộn
    print("  Cuộn sidebar xuống tận cuối để tìm tất cả liên hệ SQL...")
    no_new = 0
    scrolls_since_scan = 0
    for i in range(SIDEBAR_SCROLL_PASSES):
        conv_container.set_focus()
        conv_container.wheel_mouse_input(wheel_dist=-5)  # cuộn xuống mạnh hơn
        time.sleep(0.12)
        scrolls_since_scan += 1

        if scrolls_since_scan >= 3:
            prev_count = len(sql_names)
            scan_children()
            scrolls_since_scan = 0
            if len(sql_names) > prev_count:
                no_new = 0
                print(f"  Cuộn #{i+1}: tìm thêm! Tổng: {len(sql_names)}")
            else:
                no_new += 1
            # Chỉ dừng nếu 20 lần quét liên tiếp không tìm thêm ai
            if no_new >= 20:
                print(f"  Đã cuộn {i+1} lần, không tìm thêm. Dừng quét sidebar.")
                break

        if (i + 1) % 50 == 0 and no_new < 20:
            print(f"  Đang cuộn sidebar... #{i+1}, tìm được {len(sql_names)} liên hệ SQL")

    # Bước 4: Cuộn sidebar về đầu (cho lần click đầu tiên)
    print("  Cuộn sidebar về đầu...")
    conv_container.set_focus()
    for _ in range(300):
        conv_container.wheel_mouse_input(wheel_dist=10)
        time.sleep(0.02)
    time.sleep(0.5)

    names = sorted(sql_names)
    print(f"  Tổng cộng {len(names)} liên hệ SQL:")
    for n in names:
        print(f"    - {n}")
    return names


def click_contact(dlg, target_name):
    """
    Click vào liên hệ target_name trong sidebar.
    Nếu không thấy trong viewport hiện tại, cuộn sidebar để tìm.
    """
    conv_list = dlg.child_window(auto_id="conversationList", control_type="Table")
    conv_container = dlg.child_window(auto_id="conversationListId", control_type="Group")

    def try_click():
        for child in conv_list.children(control_type="Text"):
            if child.window_text() == target_name:
                rect = child.rectangle()
                if rect.width() > 0 and rect.left > 0:
                    child.click_input()
                    return True
        return False

    # Thử click trực tiếp
    if try_click():
        return True

    # Cuộn sidebar xuống để tìm
    for _ in range(SIDEBAR_SCROLL_PASSES):
        conv_container.set_focus()
        conv_container.wheel_mouse_input(wheel_dist=-3)
        time.sleep(0.3)
        if try_click():
            return True

    # Nếu không thấy, cuộn ngược lên
    for _ in range(SIDEBAR_SCROLL_PASSES * 2):
        conv_container.set_focus()
        conv_container.wheel_mouse_input(wheel_dist=5)
        time.sleep(0.3)
        if try_click():
            return True

    return False


# ===== TRÍCH XUẤT TIN NHẮN =====

def capture_visible(msg_view, center_x):
    """
    Thu thập tất cả text element đang hiển thị thực sự trong messageView.
    Lọc bỏ: text rỗng, biểu tượng PUA, phần tử có width=0.
    Sắp xếp theo rect_top (trên → dưới = cũ → mới).
    """
    items = []
    for child in msg_view.children(control_type="Text"):
        rect = child.rectangle()
        if rect.width() <= 0 or rect.left <= 0:
            continue
        text = child.window_text()
        if not text or not text.strip():
            continue
        if is_pua_only(text):
            continue
        items.append({
            "text": text,
            "sender": get_sender(rect.left, center_x),
            "rect_top": rect.top,
            "rect_left": rect.left,
        })
    # SẮP XẾP THEO RECT_TOP - cốt lõi cho thuật toán khử trùng
    items.sort(key=lambda x: x["rect_top"])
    return items


def find_overlap_length(newer_batch, older_accumulated):
    """
    Tìm độ dài phần chồng lặp dài nhất giữa:
    - Hậu tố (suffix) của newer_batch (batch cuộn lên, chứa tin cũ hơn)
    - Tiền tố (prefix) của older_accumulated (dữ liệu tích lũy, chứa tin mới hơn)
    So sánh dựa trên cặp (text, sender), bỏ qua tọa độ (vì tọa độ thay đổi sau cuộn).
    """
    nf = [(m["text"], m["sender"]) for m in newer_batch]
    of = [(m["text"], m["sender"]) for m in older_accumulated]
    best = 0
    limit = min(len(nf), len(of))
    for length in range(1, limit + 1):
        if nf[-length:] == of[:length]:
            best = length
    return best


def merge_batches(accumulated, new_batch):
    """
    Ghép new_batch (tin cũ hơn từ cuộn lên) vào accumulated (tin mới hơn đã có).
    Tự động phát hiện và loại bỏ phần chồng lặp.
    Nếu không tìm thấy chồng lặp → giữ nguyên cả hai và đánh dấu possible_gap.
    """
    if not accumulated:
        return list(new_batch)
    if not new_batch:
        return accumulated

    overlap = find_overlap_length(new_batch, accumulated)
    if overlap > 0:
        merged = new_batch[:-overlap] + accumulated
        return merged
    else:
        # Không tìm thấy chồng lặp → ghép nguyên, đánh dấu ranh giới
        for m in new_batch:
            m["possible_gap"] = True
        return new_batch + accumulated


def extract_conversation(dlg, conv_name):
    """
    Trích xuất toàn bộ lịch sử tin nhắn của cuộc trò chuyện đang mở.
    Bước 1: Cuộn XUỐNG tận cuối để đảm bảo bắt đầu từ tin mới nhất.
    Bước 2: Cuộn LÊN liên tục, thu thập và ghép nối cho đến khi hết tin mới.
    """
    try:
        msg_view = dlg.child_window(auto_id="messageView", control_type="Group")
        if not msg_view.exists(timeout=3):
            print("    Không tìm thấy messageView.")
            return [], 0, "messageView_not_found"
    except Exception as e:
        return [], 0, str(e)

    # BƯỚC QUAN TRỌNG: Cuộn chat XUỐNG TẬN CUỐI trước
    print("    Cuộn chat xuống cuối cùng...")
    try:
        msg_view.set_focus()
        for _ in range(100):
            msg_view.wheel_mouse_input(wheel_dist=-10)  # cuộn xuống mạnh
            time.sleep(0.05)
        time.sleep(1.5)
    except Exception:
        pass

    rect = msg_view.rectangle()
    center_x = rect.left + rect.width() / 2

    accumulated = []
    empty_scrolls = 0
    total_scrolls = 0
    stop_reason = "unknown"

    try:
        while empty_scrolls < EMPTY_SCROLL_LIMIT and total_scrolls < MAX_CHAT_SCROLLS:
            batch = capture_visible(msg_view, center_x)

            if not accumulated:
                accumulated = batch
                if batch:
                    empty_scrolls = 0
            else:
                prev_len = len(accumulated)
                accumulated = merge_batches(accumulated, batch)
                if len(accumulated) <= prev_len:
                    empty_scrolls += 1
                else:
                    empty_scrolls = 0

            if total_scrolls % 5 == 0:
                print(f"    Cuộn #{total_scrolls}: {len(accumulated)} tin (trống liên tiếp: {empty_scrolls})")

            if empty_scrolls >= EMPTY_SCROLL_LIMIT:
                stop_reason = "no_new_messages"
                break

            # Cuộn lên
            try:
                msg_view.set_focus()
                msg_view.wheel_mouse_input(wheel_dist=5)
            except Exception:
                try:
                    msg_view.type_keys("{PGUP}")
                except Exception:
                    stop_reason = "scroll_failed"
                    break
            time.sleep(SCROLL_WAIT_SEC)
            total_scrolls += 1

        if total_scrolls >= MAX_CHAT_SCROLLS:
            stop_reason = "max_scrolls_reached"

    except KeyboardInterrupt:
        stop_reason = "user_interrupted"
        print("    ⚠ Ctrl+C → Lưu dữ liệu đã thu...")

    # Gán metadata
    for i, m in enumerate(accumulated):
        m["capture_order"] = i
        m["conversation_name"] = conv_name
        m["timestamp_raw"] = None
        m["message_type"] = classify_element(m["text"])
        if "possible_gap" not in m:
            m["possible_gap"] = False

    print(f"    ✓ {len(accumulated)} tin, {total_scrolls} cuộn, dừng: {stop_reason}")
    return accumulated, total_scrolls, stop_reason


# ===== HÀM CHÍNH =====

def main():
    print("=" * 60)
    print("  ZALO SQL EXPORTER - Phase 2")
    print("  Tự động tìm và trích xuất lịch sử chat")
    print("  Dừng khẩn cấp: Ctrl+C")
    print("=" * 60)

    start_time = datetime.now()

    # 1. Tìm cửa sổ Zalo
    dlg = find_zalo_window()
    if not dlg:
        print("LỖI: Không tìm thấy cửa sổ Zalo PC. Hãy mở Zalo lên.")
        return
    print("✓ Đã kết nối Zalo PC.\n")

    # 2. Tìm tất cả liên hệ SQL
    sql_contacts = discover_sql_contacts(dlg)
    if not sql_contacts:
        print("Không tìm thấy liên hệ nào có 'sql' trong tên.")
        print("Hãy đảm bảo bạn đã đặt biệt danh chứa 'sql' cho các liên hệ cần trích xuất.")
        return

    # 3. Trích xuất từng cuộc trò chuyện
    all_data = []
    reports = []

    try:
        for i, name in enumerate(sql_contacts):
            print(f"\n{'─'*50}")
            print(f"[{i+1}/{len(sql_contacts)}] Mở: {name}")

            if not click_contact(dlg, name):
                msg = f"Không thể click vào '{name}'. Bỏ qua."
                print(f"  ⚠ {msg}")
                reports.append({"name": name, "count": 0, "scrolls": 0, "reason": "click_failed"})
                continue

            time.sleep(2.5)  # Chờ hội thoại load

            msgs, scrolls, reason = extract_conversation(dlg, name)
            all_data.extend(msgs)
            reports.append({"name": name, "count": len(msgs), "scrolls": scrolls, "reason": reason})

            if reason == "user_interrupted":
                break

    except KeyboardInterrupt:
        print("\n⚠ Ctrl+C → Dừng toàn bộ. Lưu dữ liệu đã thu thập...")

    # 4. Lưu kết quả
    if all_data:
        # CSV (UTF-8 BOM cho Excel)
        fields = ["capture_order", "conversation_name", "sender", "timestamp_raw",
                   "text", "message_type", "possible_gap"]
        with codecs.open(OUTPUT_CSV, "w", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for m in all_data:
                writer.writerow({k: m.get(k) for k in fields})

        # JSON
        clean = [{k: v for k, v in m.items()
                  if not k.startswith("_") and k not in ("rect_top", "rect_left")}
                 for m in all_data]
        with codecs.open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)

    # 5. Báo cáo
    end_time = datetime.now()
    duration = end_time - start_time

    report_lines = [
        "=== BÁO CÁO LẦN CHẠY ===",
        f"Thời gian: {start_time:%H:%M:%S} → {end_time:%H:%M:%S} ({duration})",
        f"Tổng tin nhắn: {len(all_data)}",
        f"Số cuộc trò chuyện: {len(reports)}",
        "",
        "Chi tiết từng cuộc trò chuyện:",
    ]
    for r in reports:
        status = "✓" if r["count"] > 0 else "✗"
        report_lines.append(
            f"  {status} {r['name']}: {r['count']} tin, "
            f"{r['scrolls']} cuộn, dừng: {r['reason']}"
        )

    # Lưu ý quan trọng
    report_lines.extend([
        "",
        "LƯU Ý:",
        "- Số tin nhắn là tổng các text element quan sát được, bao gồm cả ngày/giờ.",
        "- Không đảm bảo đã lấy được TOÀN BỘ lịch sử.",
        "- Cột 'possible_gap' = True nghĩa là thuật toán không tìm được chồng lặp",
        "  giữa 2 lần cuộn; có thể bị mất hoặc lặp tin ở vị trí đó.",
    ])

    report_text = "\n".join(report_lines)
    print(f"\n{report_text}")

    with codecs.open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_text)

    if all_data:
        print(f"\n✓ Đã lưu: {OUTPUT_CSV}, {OUTPUT_JSON}, {REPORT_FILE}")
    else:
        print("\nKhông có dữ liệu nào được trích xuất.")


if __name__ == "__main__":
    main()
