import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import yt_dlp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models import Video
from app.smb_upload import queue_upload

logger = logging.getLogger(__name__)

# Progress tracking for active downloads
active_downloads: dict[int, dict] = {}  # worker_id -> {video_id, title, percent, speed, eta, status}

# Pause state for downloads
_downloads_paused: bool = False
_pause_event: asyncio.Event = None  # Will be initialized on first use


def _get_pause_event() -> asyncio.Event:
    """Get or create the pause event."""
    global _pause_event
    if _pause_event is None:
        _pause_event = asyncio.Event()
        _pause_event.set()  # Not paused by default
    return _pause_event


def is_downloads_paused() -> bool:
    """Check if downloads are paused."""
    return _downloads_paused


def pause_downloads():
    """Pause all downloads (current downloads will finish, new ones won't start)."""
    global _downloads_paused
    _downloads_paused = True
    _get_pause_event().clear()
    logger.info("Downloads paused")


def resume_downloads():
    """Resume downloads."""
    global _downloads_paused
    _downloads_paused = False
    _get_pause_event().set()
    logger.info("Downloads resumed")


def get_format_string() -> str:
    """Get yt-dlp format string based on quality setting."""
    quality = settings.video_quality

    # More flexible format selection with fallbacks
    if quality == "best":
        return "bestvideo+bestaudio/best"
    elif quality == "1080p":
        return "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    elif quality == "720p":
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    elif quality == "480p":
        return "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    else:
        return "best"


def get_download_progress() -> list[dict]:
    """Get progress of all active downloads."""
    return list(active_downloads.values())


async def reset_stuck_downloads():
    """Reset videos stuck in 'downloading' status to 'pending'.

    Called on startup to recover from crashes/restarts where downloads
    were interrupted mid-way.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Video).where(Video.status == "downloading")
        )
        stuck_videos = result.scalars().all()

        if stuck_videos:
            for video in stuck_videos:
                video.status = "pending"
                logger.warning(f"Reset stuck download: {video.youtube_id} - {video.title}")
            await session.commit()
            logger.info(f"Reset {len(stuck_videos)} stuck download(s) to pending")


async def check_orphan_downloads():
    """Check for downloads marked as 'downloading' but with no active worker.

    This catches cases where a download worker crashed/died silently.
    """
    # Get video IDs currently being tracked by workers
    active_video_ids = {d.get('video_id') for d in active_downloads.values() if d.get('video_id')}

    async with async_session() as session:
        result = await session.execute(
            select(Video).where(Video.status == "downloading")
        )
        downloading_videos = result.scalars().all()

        orphans = []
        for video in downloading_videos:
            if video.id not in active_video_ids:
                orphans.append(video)
                video.status = "pending"
                logger.warning(f"Found orphan download (no active worker): {video.youtube_id} - {video.title}")

        if orphans:
            await session.commit()
            logger.info(f"Reset {len(orphans)} orphan download(s) to pending")
            # Re-queue them
            for video in orphans:
                await queue_download(video.id, video.duration)


# Watchdog task reference
_watchdog_task: asyncio.Task = None


async def download_watchdog():
    """Background task that periodically checks for stuck/orphan downloads."""
    logger.info("Download watchdog started")
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        try:
            await check_orphan_downloads()
        except Exception as e:
            logger.error(f"Watchdog error: {e}", exc_info=True)


async def start_download_watchdog():
    """Start the download watchdog task."""
    global _watchdog_task
    _watchdog_task = asyncio.create_task(download_watchdog())
    logger.info("Download watchdog task created")


def get_active_download_counts() -> dict:
    """Get count of active video and shorts downloads."""
    video_count = sum(1 for w in active_downloads.values() if w.get('worker_id', 0) < 100)
    shorts_count = sum(1 for w in active_downloads.values() if w.get('worker_id', 0) >= 100)
    return {
        'videos': video_count,
        'shorts': shorts_count,
        'max_videos': settings.max_concurrent_downloads,
        'max_shorts': settings.max_concurrent_shorts_downloads,
    }


def _create_progress_hook(worker_id: int, video_title: str, video_id: int):
    """Create a progress hook function for yt-dlp."""
    last_broadcast = {"time": 0}

    def progress_hook(d):
        now = time.time()
        status = d.get("status", "")

        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            speed = d.get("speed", 0) or 0
            eta = d.get("eta", 0) or 0

            # Calculate percent
            percent = (downloaded / total * 100) if total > 0 else 0

            active_downloads[worker_id] = {
                "worker_id": worker_id,
                "video_id": video_id,
                "title": video_title[:50],
                "status": "downloading",
                "percent": round(percent, 1),
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "speed": speed,
                "eta": eta,
            }

            # Broadcast progress via WebSocket (throttled to every 0.5s)
            if now - last_broadcast["time"] > 0.5:
                last_broadcast["time"] = now
                try:
                    import asyncio
                    from app.api.websocket import manager
                    speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed else ""
                    asyncio.create_task(manager.send_download_progress(video_id, round(percent, 1), speed_str))
                except Exception:
                    pass

        elif status == "finished":
            active_downloads[worker_id] = {
                "worker_id": worker_id,
                "video_id": video_id,
                "title": video_title[:50],
                "status": "processing",
                "percent": 100,
                "downloaded_bytes": d.get("downloaded_bytes", 0),
                "total_bytes": d.get("downloaded_bytes", 0),
                "speed": 0,
                "eta": 0,
            }

    return progress_hook


def get_download_opts(output_path: str, progress_hook=None) -> dict:
    """Get yt-dlp options for downloading."""
    opts = {
        "format": get_format_string(),
        "outtmpl": output_path,
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        "ignoreerrors": False,
        # Use player clients that don't require JS runtime
        "extractor_args": {"youtube": {"player_client": ["android_sdkless", "web_safari"]}},
        # Embed metadata (title, description, etc.) into the MP4 file
        # This makes Plex show the clean title instead of the filename
        "writethumbnail": False,
        "embedmetadata": True,
        # Subtitles: download manual subs only (no auto-generated), embed in MP4
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": ["es", "en"],
        "postprocessors": [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
            {
                "key": "FFmpegEmbedSubtitle",
            },
        ],
    }

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    return opts


async def download_video(video_id: int, worker_id: int = 0):
    """Download a video in the background."""
    logger.info(f"Starting download for video_id={video_id}")

    async with async_session() as session:
        result = await session.execute(
            select(Video).where(Video.id == video_id)
        )
        video = result.scalar_one_or_none()

        if not video:
            logger.error(f"Video not found in database: video_id={video_id}")
            return

        logger.info(f"Downloading: {video.title} ({video.youtube_id})")

        video.status = "downloading"
        video.download_attempts += 1
        await session.commit()

        # Initialize progress tracking
        active_downloads[worker_id] = {
            "worker_id": worker_id,
            "video_id": video_id,
            "title": video.title[:50],
            "status": "starting",
            "percent": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": 0,
            "eta": 0,
        }

        try:
            safe_title = "".join(c for c in video.title if c.isalnum() or c in " -_").strip()[:100]
            output_path = os.path.join(
                settings.download_dir,
                f"{video.youtube_id}_{safe_title}.%(ext)s"
            )
            logger.debug(f"Output path: {output_path}")

            url = f"https://www.youtube.com/watch?v={video.youtube_id}"
            progress_hook = _create_progress_hook(worker_id, video.title, video_id)
            opts = get_download_opts(output_path, progress_hook)

            logger.info(f"Starting yt-dlp download for {url}")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _sync_download, url, opts)

            # Find the downloaded file
            download_dir = Path(settings.download_dir)
            file_found = False
            for ext in ["mp4", "mkv", "webm"]:
                pattern = f"{video.youtube_id}_*.{ext}"
                files = list(download_dir.glob(pattern))
                if files:
                    file_path = files[0]
                    video.file_path = str(file_path)
                    video.file_size = file_path.stat().st_size
                    file_found = True
                    logger.info(f"Download completed: {file_path} ({video.file_size / 1024 / 1024:.1f} MB)")
                    break

            if not file_found:
                logger.warning(f"Download completed but file not found for {video.youtube_id}")

            # Clean up subtitle files (.vtt) - they're already embedded in the MP4
            for vtt_file in download_dir.glob(f"{video.youtube_id}_*.vtt"):
                try:
                    vtt_file.unlink()
                    logger.debug(f"Deleted subtitle file: {vtt_file}")
                except Exception as e:
                    logger.warning(f"Failed to delete subtitle file {vtt_file}: {e}")

            video.status = "completed"
            video.downloaded_at = datetime.utcnow()
            await session.commit()

            # Clean up progress tracking
            if worker_id in active_downloads:
                del active_downloads[worker_id]

            # Broadcast status change via WebSocket
            try:
                from app.api.websocket import manager
                await manager.send_status_change(video.id, "completed")
            except Exception:
                pass  # WebSocket not critical

            # Queue for SMB upload if enabled
            if file_found and settings.smb_enabled:
                await queue_upload(video.id)
            return

        except Exception as e:
            logger.error(f"Error downloading {video.youtube_id}: {e}", exc_info=True)
            video.status = "error"
            video.error_message = str(e)[:1000]

            # Clean up progress tracking on error
            if worker_id in active_downloads:
                del active_downloads[worker_id]

        await session.commit()


def _sync_download(url: str, opts: dict):
    """Synchronous download function to run in executor."""
    logger.debug(f"_sync_download called for {url}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    logger.debug(f"_sync_download completed for {url}")


# Background task queues (separate for videos and shorts)
download_queue: asyncio.Queue = asyncio.Queue()  # Regular videos
shorts_download_queue: asyncio.Queue = asyncio.Queue()  # Shorts
download_workers: list[asyncio.Task] = []
shorts_download_workers: list[asyncio.Task] = []


async def download_worker(worker_id: int, is_shorts: bool = False):
    """Worker that processes downloads from the queue."""
    queue = shorts_download_queue if is_shorts else download_queue
    label = "shorts" if is_shorts else "video"
    logger.info(f"Download worker {worker_id} ({label}) started")
    while True:
        video_id = await queue.get()

        # Wait if downloads are paused
        pause_event = _get_pause_event()
        if not pause_event.is_set():
            logger.info(f"Worker {worker_id} ({label}) waiting - downloads paused")
            await pause_event.wait()
            logger.info(f"Worker {worker_id} ({label}) resuming")

        logger.info(f"Worker {worker_id} ({label}) processing download: video_id={video_id}")
        try:
            await download_video(video_id, worker_id)
        except Exception as e:
            logger.error(f"Worker {worker_id} ({label}) error downloading {video_id}: {e}", exc_info=True)
            # Clean up on exception
            if worker_id in active_downloads:
                del active_downloads[worker_id]
        finally:
            queue.task_done()


async def start_download_worker():
    """Start multiple background download workers for concurrent downloads."""
    global download_workers, shorts_download_workers

    # Start video workers
    num_video_workers = settings.max_concurrent_downloads
    logger.info(f"Starting {num_video_workers} video download workers...")
    for i in range(num_video_workers):
        worker = asyncio.create_task(download_worker(i + 1, is_shorts=False))
        download_workers.append(worker)
    logger.info(f"{num_video_workers} video download workers started")

    # Start shorts workers
    num_shorts_workers = settings.max_concurrent_shorts_downloads
    logger.info(f"Starting {num_shorts_workers} shorts download workers...")
    for i in range(num_shorts_workers):
        # Worker IDs for shorts start at 100 to avoid conflicts
        worker = asyncio.create_task(download_worker(100 + i + 1, is_shorts=True))
        shorts_download_workers.append(worker)
    logger.info(f"{num_shorts_workers} shorts download workers started")

    # Load pending downloads from database into queue
    await load_pending_downloads()

    # Retry failed downloads with recoverable errors
    await retry_failed_downloads()


def is_short_video(duration: int) -> bool:
    """Check if video is a Short based on duration."""
    return duration > 0 and duration <= settings.shorts_max_duration


async def load_pending_downloads():
    """Load videos with status 'pending' from database into download queue."""
    # First reset any stuck downloads
    await reset_stuck_downloads()

    async with async_session() as session:
        result = await session.execute(
            select(Video)
            .where(Video.status == "pending")
            .order_by(Video.created_at.asc())
        )
        pending_videos = result.scalars().all()

        if pending_videos:
            videos_count = 0
            shorts_count = 0
            for video in pending_videos:
                if is_short_video(video.duration):
                    await shorts_download_queue.put(video.id)
                    shorts_count += 1
                else:
                    await download_queue.put(video.id)
                    videos_count += 1
            logger.info(f"Queued {videos_count} pending videos and {shorts_count} pending shorts")
        else:
            logger.info("No pending downloads to load")


async def queue_download(video_id: int, duration: int = 0):
    """Add a video to the appropriate download queue based on duration."""
    if is_short_video(duration):
        logger.info(f"Queuing short download: video_id={video_id}")
        await shorts_download_queue.put(video_id)
    else:
        logger.info(f"Queuing video download: video_id={video_id}")
        await download_queue.put(video_id)


# Errors that are recoverable and worth retrying
RECOVERABLE_ERRORS = [
    "Broken pipe",
    "timed out",
    "Connection reset",
    "Connection refused",
    "Network is unreachable",
    "Temporary failure",
    "503",
    "502",
    "500",
]

MAX_DOWNLOAD_ATTEMPTS = 3


async def retry_failed_downloads():
    """Retry downloads that failed with recoverable errors."""
    from sqlalchemy import and_, or_

    async with async_session() as session:
        # Build conditions for recoverable errors
        error_conditions = [Video.error_message.ilike(f"%{err}%") for err in RECOVERABLE_ERRORS]

        result = await session.execute(
            select(Video)
            .where(
                and_(
                    Video.status == "error",
                    Video.download_attempts < MAX_DOWNLOAD_ATTEMPTS,
                    or_(*error_conditions)
                )
            )
            .order_by(Video.created_at.asc())
        )
        failed_videos = result.scalars().all()

        if failed_videos:
            logger.info(f"Retrying {len(failed_videos)} failed downloads with recoverable errors...")
            videos_count = 0
            shorts_count = 0
            for video in failed_videos:
                video.status = "pending"
                video.error_message = None
                if is_short_video(video.duration):
                    await shorts_download_queue.put(video.id)
                    shorts_count += 1
                else:
                    await download_queue.put(video.id)
                    videos_count += 1
            await session.commit()
            logger.info(f"Queued {videos_count} videos and {shorts_count} shorts for retry")
        else:
            logger.info("No recoverable failed downloads to retry")
