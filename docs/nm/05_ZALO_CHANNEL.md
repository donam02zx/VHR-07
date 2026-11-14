# 05 — Kênh Zalo Bot Platform

> Nguồn: tài liệu của bên thứ ba (các công cụ đã tích hợp), CHƯA kiểm chứng với docs chính thức. Phần "chưa kiểm chứng" phải thử bằng token thật.

## ĐÃ KIỂM CHỨNG (2026-11-14, bot thật, chat 1:1) — ưu tiên hơn mọi mục bên dưới
- `getMe`: `POST .../bot<TOKEN>/getMe` → `{"ok":true,"result":{id, account_name, account_type, can_join_groups, display_name}}`.
- `getUpdates`: `POST`, `result` là **MỘT sự kiện (object, không phải list)**. Đọc xong sự kiện bị lấy khỏi hàng đợi (không đọc lại được, không có `offset`).
  Chưa có tin mới → `{"ok":false,"description":"Request timeout","error_code":408}`: **bình thường**, poller gọi lại ngay, không log như lỗi.
- Tin chữ: `event_name="message.text.received"`, `message.message_type="CHAT_TEXT"`, `message.text`.
- Tin ảnh: `event_name="message.image.received"`, `message.message_type="CHAT_PHOTO"`, `message.photo_url` (tải thẳng bằng GET, không cần đăng nhập), `message.caption` (có thể vắng).
- Chung: `message.chat.id`, `message.chat.chat_type` (`"PRIVATE"`), `message.message_id` (duy nhất → `event_key`), `message.date` (mili giây), `message.from.id/display_name/is_bot`. Chat 1:1: `chat.id == from.id`.
- `sendMessage`: body JSON `{"chat_id": "...", "text": "..."}` → `{"ok":true,"result":{message_id,date,message_type}}`. Thiếu `chat_id` → 400 `"The chat_id must not be empty"`.
- Mẫu thật: `docs/nm/samples/update_text.json`, `update_photo.json`.

## Đã biết từ nguồn thứ ba (độ tin cậy khá)
- Tạo bot tại bot.zaloplatforms.com. Token dạng `numeric_id:secret`; với bot Marketplace token dùng được có thể nằm trong tin nhắn chào của bot.
- Mọi lệnh: `POST https://bot-api.zaloplatforms.com/bot<TOKEN>/<method>`. Phương thức đã thấy: `getMe`, `getUpdates`, `sendMessage`, `sendPhoto`, `setWebhook`, `deleteWebhook`.
- `getUpdates` (long-polling) và webhook loại trừ nhau. Nếu `getUpdates` rỗng bất thường → gọi `deleteWebhook`.
- Tin nhắn gửi đi tối đa 2000 ký tự → phải cắt đoạn. Không markdown.
- Trong nhóm bot chỉ được kích hoạt khi bị @nhắc tên. Một số bot Marketplace KHÔNG thêm được vào nhóm.
- Ảnh đến: hỗ trợ hạn chế, phải kiểm chứng.

## CHƯA kiểm chứng (đừng đoán)
- Tham số `timeout` của `getUpdates` (client hiện KHÔNG gửi, chỉ đặt timeout HTTP phía mình).
- `sendPhoto` (client ném `NotImplementedError` ở chế độ `zalo` cho tới khi có mẫu).
- Hành vi trong nhóm (`can_join_groups=true` nhưng chưa thử): `parse_update` bỏ qua `chat_type` khác `PRIVATE`.
- Giới hạn tốc độ; loại tin khác (sticker, file): `parse_update` trả `None`.
- Xoá/thu hồi tin nhắn: giả định KHÔNG làm được. Tin bị gỡ → DB đổi trạng thái và bot trả lời "Tin #N đã được gỡ".
- Nhắn riêng cho người chưa từng chat với bot: coi là không được.

## Mẫu thực tế (BẮT BUỘC có trước khi viết parser)
Người dùng chạy `curl` thật và lưu JSON vào `docs/nm/samples/`:
- `update_text.json`, `update_photo.json`, (nếu có) `update_group_mention.json`, `getMe.json`
**Nếu chưa có file mẫu, dừng và hỏi người dùng.** Parser `parse_update()` viết dựa trên file mẫu, kèm test dùng chính file đó.

## Giao diện module `channels/zalo.py` (giữ nhỏ)
```python
@dataclass
class Inbound:        # đã chuẩn hoá
    event_key: str    # duy nhất cho mỗi update, dùng với processed_events
    chat_id: str
    user_id: str
    display_name: str | None
    text: str
    image_ref: str | None
    is_group: bool

class ZaloClient:
    async def get_updates(self) -> list[dict]: ...   # 0 hoặc 1 sự kiện; 408 → []
    def parse_update(self, raw: dict) -> Inbound | None: ...   # None nếu loại tin không hỗ trợ (sticker...)
    async def send_text(self, chat_id: str, text: str) -> None: ...   # tự cắt 2000 ký tự
    async def send_photo(self, chat_id: str, photo: str, caption: str = "") -> None: ...
    async def download_image(self, image_ref: str) -> bytes: ...
```
- Dùng `httpx.AsyncClient`, timeout rõ ràng, thử lại tối đa 2 lần khi lỗi mạng/5xx. Token lấy từ `get_settings()`, không bao giờ log token.
- Chế độ giả lập: `CHANNEL_MODE=sim` thì `send_text` ghi vào danh sách trong bộ nhớ + in log (để test và chạy khi không có token).

## Poller (`channels/poller.py`)
Vòng lặp async: `get_updates` → với mỗi update: parse → bỏ qua nếu `event_key` đã có trong `processed_events` → gọi `dispatcher.handle(inbound)`.
Một lỗi trong handler KHÔNG được làm chết vòng lặp: bắt, log (kèm event_key), chạy tiếp. Khi lỗi mạng: chờ backoff 1s, 2s, 4s (tối đa 30s).
