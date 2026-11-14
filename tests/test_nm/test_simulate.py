"""T11 — scripts/seed.py (idempotent, --moderator) và scripts/simulate.py (4 cảnh demo, sim)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from src.services import db

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"nm_script_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path) -> None:
    db.reset_for_tests(tmp_path / "nm.db")


def test_seed_creates_published_and_is_idempotent() -> None:
    seed = load("seed")
    assert seed.seed() == len(seed.LISTINGS)
    assert seed.seed() == 0
    published = db.search_candidates()
    assert len(published) == len(seed.LISTINGS)
    titles = " ".join(r["title"].lower() for r in published)
    assert titles.count("xe đạp") >= 2
    for word in ("tủ lạnh", "bàn học", "nồi chiên không dầu"):
        assert word in titles


def test_seed_main_sets_moderator(tmp_path: Path) -> None:
    seed = load("seed")
    assert seed.main(["--db", str(tmp_path / "other.db"), "--moderator", "zu-mod"]) == 0
    assert db.get_user_by_zalo("zu-mod")["role"] == "moderator"
    assert len(db.search_candidates()) == len(seed.LISTINGS)


async def test_simulate_four_scenes_pass(tmp_path: Path) -> None:
    sim = load("simulate")
    lines: list[str] = []
    code = await sim.run(tmp_path / "sim.db", tmp_path, out=lines.append)
    text = "\n".join(lines)
    assert code == 0, text
    for n in range(1, 5):
        assert f"=== Cảnh {n}:" in text
    assert "SAI" not in text
    assert "TẤT CẢ 4 CẢNH ĐÚNG" in text
