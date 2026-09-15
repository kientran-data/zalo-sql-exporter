# Zalo SQL Exporter - Khảo sát Phase 1

Dự án này sử dụng Windows UI Automation (`pywinauto`) để đọc nội dung hiển thị trên cửa sổ Zalo PC.

## Cài đặt

Mở PowerShell và chạy các lệnh sau trong thư mục `c:\Users\Admin\Documents\work\kien\zalo-sql-exporter`:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install pywinauto
```

*(Lưu ý: Quá trình cài đặt `pywinauto` và `pywin32` có thể mất một lúc tùy thuộc vào mạng).*

## Bước 1: Khảo sát cấu trúc UI (Chạy trước)

Để không giả định framework hoặc cấu trúc dữ liệu của Zalo (có thể là Electron, Qt, hoặc native), chúng ta cần xuất cây UI (Accessibility Tree) ra file log để phân tích xem có đọc được nội dung tin nhắn không.

**Cách chạy:**
1. Mở Zalo PC và đăng nhập.
2. Chọn một cuộc trò chuyện bất kỳ và để cửa sổ Zalo ở trạng thái đang mở.
3. Chạy lệnh sau trên terminal/PowerShell:
   ```powershell
   .\.venv\Scripts\activate
   python dump_zalo_ui.py
   ```
4. Kiểm tra file `zalo_ui_tree.txt` được tạo ra. Trong file này, hãy tìm kiếm một vài đoạn tin nhắn hiện đang hiển thị trên màn hình Zalo của bạn xem nó có xuất hiện dưới dạng `title` hay thuộc tính nào của control không.

**Hãy cho tôi biết kết quả (hoặc cung cấp một phần nội dung của file `zalo_ui_tree.txt` chứa đoạn tin nhắn)**. Nếu cây UI hiển thị được nội dung, chúng ta sẽ viết script lấy dữ liệu (extractor) ngay ở bước sau. Nếu không, chúng ta phải dừng và tìm cách khác.

## Bước 2: Chạy thử bản lấy dữ liệu (Phase 1 Extractor)

Từ file UI tree đã khảo sát được, tôi xác nhận **Zalo CÓ xuất nội dung tin nhắn** ra accessibility tree thông qua container `messageView`. Zalo sử dụng cơ chế "ảo hóa" (virtualization) nên những tin nhắn bị cuộn khuất sẽ có tọa độ ẩn (width=0).

Script `zalo_extractor.py` sẽ thực hiện đúng yêu cầu Phase 1 của bạn:
1. Đọc tất cả các thành phần văn bản đang **hiển thị thực tế** trên màn hình.
2. Dựa vào tọa độ X của đoạn text so với tâm màn hình để phân biệt tin nhắn của "Mình" (Me) nằm bên phải và của "Người kia" (Other) nằm bên trái.
3. Tự động cuộn lên (PageUp / Wheel) tối đa 3 lần để lấy thêm tin nhắn cũ bị khuất.
4. Ghi nhận dữ liệu ra `zalo_extracted.json` và `zalo_extracted.csv` (hỗ trợ UTF-8 BOM cho Excel).
5. Chưa lọc trùng lắp thông minh ở bước này (vì tin nhắn text có thể giống hệt nhau), chỉ thu thập thô mọi thứ quan sát được đúng thứ tự hiển thị.

**Cách chạy lấy dữ liệu:**
1. Đảm bảo Zalo đang mở và đang ở trong một cuộc trò chuyện.
2. Chạy lệnh:
   ```powershell
   python zalo_extractor.py
   ```
3. Script sẽ tự focus vào cửa sổ Zalo, cuộn 3 lần, và kết xuất dữ liệu.
4. Mở file `zalo_extracted.csv` (bằng Excel) để xem thành quả. 

**Kết quả:**
- **Đọc được**: Nội dung tin nhắn (bao gồm cả emoji), dấu thời gian rời rạc, phân biệt được người gửi dựa theo tọa độ trái/phải.
- **Chưa đọc được**: Zalo không gắn liền thời gian/người gửi vào thành một cục (node) duy nhất cho mỗi tin nhắn, mà render mọi thứ như một danh sách text phẳng. ID hội thoại và message ID cũng không được lộ ra.
- **Lệnh cần chạy**: Bạn hãy chạy `python zalo_extractor.py` và kiểm tra file CSV, sau đó phản hồi lại nếu kết quả đã đáp ứng yêu cầu khảo sát Phase 1 để chuẩn bị cho Phase 2.
