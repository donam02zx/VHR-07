"""Chạy 4 cảnh demo (docs/nm/11) ở chế độ sim — không cần Zalo/token, không gọi mạng.

    python scripts/simulate.py              # DB tạm, tự xoá
    python scripts/simulate.py --db data/sim.db

In từng bước (tin người dùng → trả lời của bot) và kiểm tra kết quả mỗi cảnh. Thoát mã 1 nếu cảnh nào sai.
Đi đúng đường code thật: dispatcher → posting → moderation → reviewflow (giống nút Duyệt trên /console).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed as seed_mod  # noqa: E402

from src.channels.zalo import Inbound, ZaloClient  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.services import db, dispatcher, reviewflow  # noqa: E402

SELLER = "sim-nguoi-ban-A"


class Demo:
    def __init__(self, workdir: Path, out: Callable[[str], None]) -> None:
        settings = get_settings().model_copy(update={"channel_mode": "sim"})  # luôn sim, kể cả .env đặt zalo
        self.client = ZaloClient(settings)
        self.workdir = workdir
        self.out = out
        self.seq = 0
        self.failures: list[str] = []

    def image(self, name: str) -> str:
        path = self.workdir / name
        path.write_bytes(b"\xff\xd8 sim image " + name.encode())  # stub AI không đọc nội dung ảnh
        return str(path)

    async def say(self, text: str = "", image: str | None = None) -> list[str]:
        self.seq += 1
        shown = f"[ảnh {Path(image).name}] {text}".strip() if image else text
        self.out(f"  A  > {shown}")
        before = len(self.client.sent)
        await dispatcher.handle(Inbound(f"sim:{self.seq}", SELLER, SELLER, "Người bán A", text, image, False),
                                self.client)
        replies = []
        for s in self.client.sent[before:]:
            who = "bot" if s.chat_id == SELLER else f"bot→{s.chat_id}"
            self.out("  " + who + " < " + s.text.replace("\n", "\n" + " " * (len(who) + 5)))
            replies.append(s.text)
        return replies

    def check(self, scene: str, ok: bool, what: str) -> None:
        self.out(f"  {'OK ' if ok else 'SAI'} {what}")
        if not ok:
            self.failures.append(f"{scene}: {what}")

    def current_listing_id(self) -> int | None:
        return db.get_conversation(SELLER)["listing_id"]

    async def scene1(self) -> None:
        self.out("\n=== Cảnh 1: Đăng tin thuận lợi ===")
        r = await self.say("Xe đạp thể thao còn mới", self.image("xe_dap.jpg"))
        lid = self.current_listing_id()
        self.check("1", bool(r) and r[0].startswith("Bản nháp tin #") and "Giá gợi ý" in r[0], "bot trả bản nháp + giá gợi ý")
        r = await self.say("sửa giá 1tr2")
        self.check("1", bool(r) and "1.200.000 đ" in r[0], "giá đổi thành 1.200.000 đ")
        r = await self.say("ok")
        self.check("1", f"Tin #{lid} đã được đăng." in r, f"tin #{lid} đã đăng")

    async def scene2(self) -> None:
        self.out("\n=== Cảnh 2: Tin bị từ chối tự động ===")
        await self.say("Thanh lý thuốc lá điện tử còn nguyên hộp", self.image("vi_pham.jpg"))
        lid = self.current_listing_id()
        r = await self.say("ok")
        self.check("2", bool(r) and r[0].startswith(f"Tin #{lid} không được đăng:"), "bot từ chối kèm lý do")
        self.check("2", db.get_listing(lid)["status"] == "rejected", "DB: rejected")

    async def scene3(self) -> None:
        self.out("\n=== Cảnh 3: Hàng chờ và người duyệt ===")
        await self.say("Bán nồi cơm điện, đặt cọc trước mới giữ hàng", self.image("noi_com.jpg"))
        lid = self.current_listing_id()
        r = await self.say("ok")
        self.check("3", f"Tin #{lid} đang chờ người duyệt, bạn sẽ được báo." in r, "bot: đang chờ người duyệt")
        pending = [x for x in db.list_reviews() if x["listing_id"] == lid]
        self.check("3", len(pending) == 1, "tin xuất hiện trong hàng chờ /console")
        if not pending:
            return
        p = pending[0]
        self.out(f"  [console] #{lid} '{p['title']}' điểm {p['score']:.2f} — {p['reason']} → bấm Duyệt")
        before = len(self.client.sent)
        _, status, replies = reviewflow.decide(p["id"], "approved", "console")
        for reply in replies:
            await self.client.send_text(reply.chat_id, reply.text)
        for s in self.client.sent[before:]:
            self.out(f"  bot < {s.text}" if s.chat_id == SELLER else f"  bot→{s.chat_id} < {s.text}")
        self.check("3", status == "published" and any(f"Tin #{lid} đã được đăng." == s.text
                                                       for s in self.client.sent[before:]), "A nhận báo đã đăng")

    async def scene4(self) -> None:
        self.out("\n=== Cảnh 4: Tìm kiếm ===")
        r = await self.say("/tim xe dap")
        self.check("4", bool(r) and r[0].startswith("Tìm thấy") and r[0].count("Xe đạp") >= 2,
                   "kết quả có các tin xe đạp")
        masked = next((x for x in db.search_candidates() if "0912" in (x["description"] or "")), None)
        if masked is None:
            self.check("4", False, "có tin mẫu chứa SĐT (chạy seed)")
            return
        r = await self.say(f"/xem {masked['id']}")
        self.check("4", bool(r) and "09xx xxx 678" in r[0] and "0912 345 678" not in r[0], "SĐT trong mô tả đã che")


async def run(db_path: Path, workdir: Path, out: Callable[[str], None] = print) -> int:
    db.use_db(db_path)
    created = seed_mod.seed()
    out(f"DB: {db_path} (seed thêm {created} tin)")
    demo = Demo(workdir, out)
    for scene in (demo.scene1, demo.scene2, demo.scene3, demo.scene4):
        await scene()
    out("\n" + ("TẤT CẢ 4 CẢNH ĐÚNG" if not demo.failures else "CẢNH SAI:\n- " + "\n- ".join(demo.failures)))
    return 0 if not demo.failures else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="file SQLite (mặc định: DB tạm, tự xoá)")
    args = parser.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="nm-sim-") as tmp:
        db_path = Path(args.db) if args.db else Path(tmp) / "sim.db"
        return asyncio.run(run(db_path, Path(tmp)))


if __name__ == "__main__":
    sys.exit(main())
