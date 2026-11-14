# 05 — Kênh Zalo Bot Platform

> Nguồn: tài liệu của bên thứ ba (các công cụ đã tích hợp), CHƯA kiểm chứng với docs chính thức. Phần "chưa kiểm chứng" phải thử bằng token thật.

## Đã biết (độ tin cậy khá)
- Tạo bot tại bot.zaloplatforms.com. Token dạng `numeric_id:secret`; với bot Marketplace token dùng được có thể nằm trong tin nhắn chào của bot.
- Mọi lệnh: `POST https://bot-api.zaloplatforms.com/bot<TOKEN>/<method>`. Phương thức đã thấy: `getMe`, `getUpdates`, `sendMessage`, `sendPhoto`, `setWebhook`, `deleteWebhook`.
- `getUpdates` (long-polling) và webhook loại trừ nhau. Nếu `getUpdates` rỗng bất thường → gọi `deleteWebhook`.
- Tin nhắn gửi đi tối đa 2000 ký tự → phải cắt đoạn. Không markdown.
- Trong nhóm bot chỉ được kích hoạt khi bị @nhắc tên. Một số bot Marketplace KHÔNG thêm được vào nhóm.
- Ảnh đến: hỗ trợ hạn chế, phải kiểm chứng.

## CHƯA kiểm chứng (đừng đoán; xem mục "Mẫu thực tế")
- Tên trường chính xác của body `sendMessage` (nhiều khả năng `chat_id`, `text`) và `getUpdates` (`timeout`, `offset`?).
- Cấu trúc JSON của một update (nơi chứa `chat.id`, `from.id`, text, ảnh).
- Cách lấy file ảnh người dùng gửi (URL trực tiếp hay `getFile`).
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
    async def get_updates(self, offset: int | None, timeout_s: int = 30) -> list[dict]: ...
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
