import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api import reviews
from src.api.routes import router
from src.channels.poller import Poller
from src.channels.sample_capture import SampleCapture
from src.channels.zalo import ZaloClient
from src.config import get_settings
from src.services import db, dispatcher

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    # NeighborMarket: DB + kênh nhắn tin dùng chung (docs/nm/02).
    db.init_db()
    channel = ZaloClient(settings)
    app.state.channel = channel
    poller = None
    if settings.channel_mode == "zalo":
        try:  # tên bot để bỏ "@tên bot" trong tin nhóm (05); lỗi → vẫn chạy, tin nhóm giữ nguyên chữ
            channel.bot_name = (await channel.get_me()).get("display_name")
        except Exception as exc:
            logging.getLogger("nm.main").warning("getMe lỗi, không bỏ được @tên bot: %s", type(exc).__name__)
        limit = get_settings().nm_capture_samples
        capture = SampleCapture(limit) if limit > 0 else None
        poller = Poller(channel, lambda inbound: dispatcher.handle(inbound, channel), capture=capture)
        poller.start()
    yield
    if poller is not None:
        await poller.stop()
    await channel.aclose()
    print("Shutting down...")


app = FastAPI(
    title="AI20K Agent",
    description="AI Agent built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(reviews.router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/console", include_in_schema=False)
async def console() -> FileResponse:
    """Trang duyệt tin (docs/nm/07)."""
    return FileResponse(STATIC_DIR / "console.html")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
