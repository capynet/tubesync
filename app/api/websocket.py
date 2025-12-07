import asyncio
import json
import logging
from typing import Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        if not self.active_connections:
            return

        data = json.dumps(message)
        disconnected = set()

        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(data)
                except Exception:
                    disconnected.add(connection)

            # Clean up disconnected
            self.active_connections -= disconnected

    async def send_download_progress(self, video_id: int, percent: float, speed: str = ""):
        await self.broadcast({
            "type": "download_progress",
            "video_id": video_id,
            "percent": percent,
            "speed": speed
        })

    async def send_upload_progress(self, video_id: int, percent: float, speed: str = ""):
        await self.broadcast({
            "type": "upload_progress",
            "video_id": video_id,
            "percent": percent,
            "speed": speed
        })

    async def send_status_change(self, video_id: int, status: str, error: str = None):
        msg = {
            "type": "status_change",
            "video_id": video_id,
            "status": status
        }
        if error:
            msg["error"] = error
        await self.broadcast(msg)

    async def send_stats_update(self, stats: dict):
        await self.broadcast({
            "type": "stats_update",
            **stats
        })


# Global instance
manager = ConnectionManager()
