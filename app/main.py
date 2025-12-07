import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.downloader import start_download_worker, reset_stuck_downloads, start_download_watchdog
from app.smb_upload import start_upload_worker, reset_stuck_uploads, start_upload_watchdog
from app.auto_download import start_auto_download_worker, init_sync_state
from app.api.websocket import manager
from app.api.routes import youtube, downloads, uploads, config

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting TubeSync API...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Load sync state from database
    await init_sync_state()

    # Reset any stuck downloads/uploads from previous crashes
    await reset_stuck_downloads()
    await reset_stuck_uploads()

    # Start background workers
    await start_download_worker()
    await start_upload_worker()
    await start_auto_download_worker()
    await start_download_watchdog()
    await start_upload_watchdog()
    logger.info("Background workers started")

    yield

    logger.info("Shutting down TubeSync API...")


app = FastAPI(
    title="TubeSync API",
    description="YouTube subscription downloader with SMB upload",
    version="2.0.0",
    lifespan=lifespan,
    redirect_slashes=False
)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])
app.include_router(downloads.router, prefix="/api/downloads", tags=["Downloads"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["Uploads"])
app.include_router(config.router, prefix="/api/config", tags=["Config"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle incoming messages if needed
            data = await websocket.receive_text()
            # Echo back for ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tubesync"}


# Serve static files (Vue frontend) in production
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
