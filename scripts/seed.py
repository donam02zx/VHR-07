"""Dữ liệu mẫu cho demo (docs/nm/11): 10 tin đã đăng. Chạy lặp lại không nhân đôi.

    python scripts/seed.py                          # DB theo NM_DB_PATH (mặc định data/app.db)
    python scripts/seed.py --db data/demo.db
    python scripts/seed.py --moderator <zalo_user_id>   # gán role moderator cho người duyệt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services import db  # noqa: E402

SELLERS = {"seed-cu-dan-1": "Cư dân mẫu 1", "seed-cu-dan-2": "Cư dân mẫu 2"}

# (người bán, tiêu đề, mô tả, danh mục, tình trạng, giá)
LISTINGS: list[tuple[str, str, str, str, str, int]] = [
    ("seed-cu-dan-1", "Xe đạp trẻ em 16 inch", "Bé lớn không đi nữa, còn bánh phụ. Gọi 0912 345 678.",
     "Thể thao", "Cũ 85%", 450_000),
    ("seed-cu-dan-2", "Xe đạp địa hình Giant", "Phanh đĩa, 21 tốc độ, đã bảo dưỡng.", "Thể thao", "Cũ 80%", 2_500_000),
    ("seed-cu-dan-1", "Tủ lạnh Panasonic 180 lít", "Chạy êm, chuyển nhà nên bán.", "Điện tử", "Cũ 75%", 2_200_000),
    ("seed-cu-dan-2", "Bàn học gỗ cho bé", "Kèm ghế, có ngăn kéo.", "Nội thất", "Cũ 90%", 600_000),
    ("seed-cu-dan-1", "Nồi chiên không dầu Lock&Lock 5L", "Dùng 3 tháng, còn hộp.", "Gia dụng", "Cũ 95%", 900_000),
    ("seed-cu-dan-2", "Quạt đứng Senko", "Còn tốt, 3 tốc độ.", "Gia dụng", "Cũ 80%", 250_000),
    ("seed-cu-dan-1", "Kệ sách 5 tầng", "Gỗ ép, màu trắng.", "Nội thất", "Cũ 85%", 350_000),
    ("seed-cu-dan-2", "Áo khoác gió nam size L", "Mặc 2 lần.", "Thời trang", "Như mới", 150_000),
    ("seed-cu-dan-1", "Máy xay sinh tố Philips", "Cối thuỷ tinh, đủ phụ kiện.", "Gia dụng", "Cũ 85%", 400_000),
    ("seed-cu-dan-2", "Ghế văn phòng lưới", "Có tựa đầu, ngả được.", "Nội thất", "Cũ 80%", 700_000),
]


def _exists(seller_id: int, title: str) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM listings WHERE seller_id=? AND title=?", (seller_id, title)).fetchone()
    return row is not None


def seed() -> int:
    """Tạo các tin còn thiếu ở trạng thái `published`. Trả số tin mới tạo."""
    ids = {zid: db.upsert_user(zid, name) for zid, name in SELLERS.items()}
    created = 0
    for zid, title, desc, category, condition, price in LISTINGS:
        seller_id = ids[zid]
        if _exists(seller_id, title):
            continue
        lid = db.create_listing(seller_id, title=title, description=desc, category=category, condition=condition,
                                price_vnd=price, price_low=price, price_high=price)
        for frm, to in (("draft", "awaiting_confirm"), ("awaiting_confirm", "pending_moderation"),
                        ("pending_moderation", "published")):
            if not db.set_status(lid, frm, to):
                raise RuntimeError(f"seed: không chuyển được listing {lid} {frm}->{to}")
        db.add_audit(lid, "seeded", "")
        created += 1
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="đường dẫn SQLite (mặc định NM_DB_PATH)")
    parser.add_argument("--moderator", metavar="ZALO_USER_ID", help="gán role moderator cho người dùng này")
    args = parser.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if args.db:
        db.use_db(args.db)
    else:
        db.init_db()
    created = seed()
    print(f"seed: tạo mới {created} tin, tổng {len(LISTINGS)} tin mẫu ({db.db_path()})")
    if args.moderator:
        db.set_role(args.moderator, "moderator")
        print(f"seed: {args.moderator} là moderator")
    return 0


if __name__ == "__main__":
    sys.exit(main())
