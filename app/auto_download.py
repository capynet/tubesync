"""
Auto-download module - Automatically syncs and downloads videos from subscriptions.
Uses channel tracking to avoid re-processing old videos.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models import Video, Channel, AppState
from app.downloader import queue_download

logger = logging.getLogger(__name__)

# Sync state for status display
_last_sync: Optional[datetime] = None
_last_sync_queued: int = 0
_sync_running: bool = False
_channel_count: int = 0
_sync_progress_current: int = 0
_sync_progress_total: int = 0
_sync_channel_results: list[dict] = []  # [{channel_name, videos_found}]
_sync_total_videos_found: int = 0  # Total videos found across all channels
_sync_channels_with_videos: int = 0  # Number of channels that had new videos
_sync_state_loaded: bool = False


async def _load_sync_state():
    """Load last sync state from database."""
    global _last_sync, _last_sync_queued, _sync_state_loaded

    if _sync_state_loaded:
        return

    try:
        async with async_session() as session:
            result = await session.execute(
                select(AppState).where(AppState.key == "last_sync")
            )
            state = result.scalar_one_or_none()

            if state:
                data = json.loads(state.value)
                if data.get('time'):
                    _last_sync = datetime.fromisoformat(data['time'])
                _last_sync_queued = data.get('queued', 0)

        _sync_state_loaded = True
    except Exception as e:
        logger.debug(f"Could not load sync state: {e}")
        _sync_state_loaded = True


async def _save_sync_state():
    """Save last sync state to database."""
    try:
        data = {
            'time': _last_sync.isoformat() if _last_sync else None,
            'queued': _last_sync_queued,
        }

        async with async_session() as session:
            result = await session.execute(
                select(AppState).where(AppState.key == "last_sync")
            )
            state = result.scalar_one_or_none()

            if state:
                state.value = json.dumps(data)
            else:
                state = AppState(key="last_sync", value=json.dumps(data))
                session.add(state)

            await session.commit()
    except Exception as e:
        logger.error(f"Error saving sync state: {e}")


def get_sync_status() -> dict:
    """Get current sync status for API."""
    # Note: _load_sync_state() is async, called on startup via init_sync_state()
    return {
        'running': _sync_running,
        'last_sync': _last_sync.isoformat() if _last_sync else None,
        'last_queued': _last_sync_queued,
        'channel_count': _channel_count,
        'progress_current': _sync_progress_current,
        'progress_total': _sync_progress_total,
        'channel_results': _sync_channel_results[-20:],  # Last 20 channels with videos
        'total_videos_found': _sync_total_videos_found,
        'channels_with_videos': _sync_channels_with_videos,
    }


async def init_sync_state():
    """Initialize sync state from database. Call on startup."""
    await _load_sync_state()


async def sync_subscriptions():
    """
    Sync YouTube subscriptions to local channel database.
    Returns list of channels to check for new videos.
    """
    global _channel_count

    from app.youtube_api import get_subscriptions, is_api_configured

    if not is_api_configured():
        logger.warning("YouTube API not configured")
        return []

    subs = get_subscriptions()
    if not subs:
        logger.warning("No subscriptions found")
        return []

    _channel_count = len(subs)
    channels_to_check = []

    async with async_session() as session:
        for sub in subs:
            channel_id = sub.get('channel_id')
            if not channel_id:
                continue

            # Get or create channel
            result = await session.execute(
                select(Channel).where(Channel.channel_id == channel_id)
            )
            channel = result.scalar_one_or_none()

            if not channel:
                channel = Channel(
                    channel_id=channel_id,
                    channel_name=sub.get('channel_title', 'Unknown'),
                    thumbnail=sub.get('thumbnail', ''),
                )
                session.add(channel)
                await session.commit()
                await session.refresh(channel)
            else:
                # Update name/thumbnail if changed
                if channel.channel_name != sub.get('channel_title'):
                    channel.channel_name = sub.get('channel_title', channel.channel_name)
                if channel.thumbnail != sub.get('thumbnail'):
                    channel.thumbnail = sub.get('thumbnail', channel.thumbnail)
                await session.commit()

            if channel.enabled:
                channels_to_check.append(channel)

    logger.info(f"Synced {len(subs)} subscriptions, {len(channels_to_check)} enabled")
    return channels_to_check


async def check_channel_for_new_videos(channel: Channel) -> list[dict]:
    """
    Check a channel for new videos since last check.
    Uses last_video_id to stop early when reaching known videos.
    Respects sync_days_back and sync_max_per_channel settings.
    """
    from app.youtube_api import get_recent_videos_from_channel, get_video_details, is_quota_exceeded

    if is_quota_exceeded():
        return []

    # Calculate cutoff date based on sync_days_back setting
    published_after = datetime.utcnow() - timedelta(days=settings.sync_days_back)

    # Get recent videos, stopping at the last known video
    # max_results=50 is YouTube API max, sync_days_back does the actual filtering
    videos = get_recent_videos_from_channel(
        channel.channel_id,
        max_results=50,
        stop_at_video_id=channel.last_video_id,
        published_after=published_after
    )

    if not videos:
        return []

    # Get duration details
    video_ids = [v['youtube_id'] for v in videos]
    details = get_video_details(video_ids)

    # Enrich videos with duration and filter out live streams
    enriched = []
    for video in videos:
        vid = video['youtube_id']
        if vid in details:
            info = details[vid]
            if info.get('is_live'):
                continue  # Skip live streams
            video['duration'] = info.get('duration', 0)
            video['thumbnail'] = info.get('thumbnail', video.get('thumbnail', ''))
        enriched.append(video)

    return enriched


async def process_new_videos(videos: list[dict]) -> int:
    """
    Add new videos to download queue.
    Returns number of videos queued.
    """
    if not videos:
        return 0

    queued = 0
    async with async_session() as session:
        for video in videos:
            youtube_id = video['youtube_id']

            # Check if already in database
            result = await session.execute(
                select(Video).where(Video.youtube_id == youtube_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Skip if already processed
                if existing.status in ('completed', 'pending', 'downloading'):
                    continue
                # Retry errors
                if existing.status == 'error':
                    existing.status = 'pending'
                    existing.error_message = None
                    await session.commit()
                    await queue_download(existing.id, existing.duration)
                    queued += 1
            else:
                # Create new video entry
                new_video = Video(
                    youtube_id=youtube_id,
                    title=video.get('title', 'Unknown'),
                    channel=video.get('channel', 'Unknown'),
                    duration=video.get('duration', 0),
                    thumbnail=video.get('thumbnail', ''),
                    status='pending',
                )
                session.add(new_video)
                await session.commit()
                await session.refresh(new_video)
                await queue_download(new_video.id, new_video.duration)
                queued += 1
                logger.info(f"Queued: {youtube_id} - {video.get('title', '')[:50]}")

    return queued


async def run_sync():
    """
    Main sync function - checks all channels for new videos.
    """
    global _last_sync, _last_sync_queued, _sync_running, _sync_progress_current, _sync_progress_total
    global _sync_total_videos_found, _sync_channels_with_videos

    if _sync_running:
        logger.info("Sync already running, skipping")
        return 0

    _sync_running = True
    _sync_progress_current = 0
    _sync_progress_total = 0
    _sync_channel_results.clear()
    _sync_total_videos_found = 0
    _sync_channels_with_videos = 0
    total_queued = 0

    try:
        from app.youtube_api import is_quota_exceeded

        if is_quota_exceeded():
            logger.warning("Quota exceeded, skipping sync")
            return 0

        # Sync subscriptions first
        channels = await sync_subscriptions()
        if not channels:
            logger.info("No channels to check")
            return 0

        _sync_progress_total = len(channels)
        logger.info(f"Checking {len(channels)} channels for new videos...")

        async with async_session() as session:
            for i, channel in enumerate(channels):
                _sync_progress_current = i + 1

                if is_quota_exceeded():
                    logger.warning("Quota exceeded mid-sync, stopping")
                    break

                # Rate limit: 200ms between channels
                if i > 0:
                    await asyncio.sleep(0.2)

                # Get new videos for this channel
                new_videos = await check_channel_for_new_videos(channel)

                if new_videos:
                    # Update totals
                    _sync_total_videos_found += len(new_videos)
                    _sync_channels_with_videos += 1

                    # Track channel results (last 20 for display)
                    _sync_channel_results.append({
                        'channel_name': channel.channel_name,
                        'videos_found': len(new_videos),
                    })

                    # Queue downloads
                    queued = await process_new_videos(new_videos)
                    total_queued += queued

                    # Update channel's last video tracking
                    newest_video = new_videos[0]  # Videos are newest first
                    result = await session.execute(
                        select(Channel).where(Channel.channel_id == channel.channel_id)
                    )
                    db_channel = result.scalar_one_or_none()
                    if db_channel:
                        db_channel.last_video_id = newest_video['youtube_id']
                        db_channel.last_video_date = newest_video.get('published_at')
                        db_channel.last_checked = datetime.utcnow()
                        await session.commit()
                else:
                    # Update last_checked even if no new videos
                    result = await session.execute(
                        select(Channel).where(Channel.channel_id == channel.channel_id)
                    )
                    db_channel = result.scalar_one_or_none()
                    if db_channel:
                        db_channel.last_checked = datetime.utcnow()
                        await session.commit()

                # Progress log every 20 channels
                if (i + 1) % 20 == 0:
                    logger.info(f"Progress: {i + 1}/{len(channels)} channels checked")

        # Only update last_sync after successful sync with channels
        _last_sync = datetime.utcnow()
        _last_sync_queued = total_queued
        await _save_sync_state()
        logger.info(f"Sync complete: {total_queued} new videos queued")
        return total_queued

    except Exception as e:
        logger.error(f"Sync error: {e}", exc_info=True)
        return 0

    finally:
        _sync_running = False


async def auto_sync_loop(interval_seconds: int = 3600):
    """
    Background loop that runs sync every interval.
    Default: every hour (3600 seconds).
    """
    logger.info(f"Auto-sync loop started (interval: {interval_seconds}s)")

    # Wait 30 seconds for startup
    await asyncio.sleep(30)

    while True:
        if settings.auto_download_enabled:
            try:
                await run_sync()
            except Exception as e:
                logger.error(f"Auto-sync error: {e}", exc_info=True)
        else:
            logger.debug("Auto-sync disabled, skipping")

        await asyncio.sleep(interval_seconds)


async def start_auto_download_worker(interval_seconds: int = 3600):
    """Start the auto-sync background worker."""
    asyncio.create_task(auto_sync_loop(interval_seconds))
    logger.info("Auto-sync worker started")


async def get_stats() -> dict:
    """Get download/upload statistics."""
    from datetime import date

    async with async_session() as session:
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())

        # Total counts
        total_result = await session.execute(select(func.count(Video.id)))
        total_videos = total_result.scalar()

        # By status
        completed_result = await session.execute(
            select(func.count(Video.id)).where(Video.status == "completed")
        )
        completed = completed_result.scalar()

        pending_result = await session.execute(
            select(func.count(Video.id)).where(Video.status == "pending")
        )
        pending = pending_result.scalar()

        downloading_result = await session.execute(
            select(func.count(Video.id)).where(Video.status == "downloading")
        )
        downloading = downloading_result.scalar()

        error_result = await session.execute(
            select(func.count(Video.id)).where(Video.status == "error")
        )
        errors = error_result.scalar()

        # Today's downloads
        today_downloaded_result = await session.execute(
            select(func.count(Video.id)).where(
                and_(
                    Video.status == "completed",
                    Video.downloaded_at >= today_start
                )
            )
        )
        today_downloaded = today_downloaded_result.scalar()

        # Upload stats
        uploaded_result = await session.execute(
            select(func.count(Video.id)).where(Video.upload_status == "uploaded")
        )
        uploaded = uploaded_result.scalar()

        upload_pending_result = await session.execute(
            select(func.count(Video.id)).where(
                and_(
                    Video.status == "completed",
                    Video.upload_status.in_(["pending", "uploading"])
                )
            )
        )
        upload_pending = upload_pending_result.scalar()

        upload_error_result = await session.execute(
            select(func.count(Video.id)).where(Video.upload_status == "error")
        )
        upload_errors = upload_error_result.scalar()

        # Today's uploads
        today_uploaded_result = await session.execute(
            select(func.count(Video.id)).where(
                and_(
                    Video.upload_status == "uploaded",
                    Video.uploaded_at >= today_start
                )
            )
        )
        today_uploaded = today_uploaded_result.scalar()

        # Total file size
        size_result = await session.execute(
            select(func.sum(Video.file_size)).where(Video.file_size.isnot(None))
        )
        total_size = size_result.scalar() or 0

        # Channel count
        channel_count_result = await session.execute(
            select(func.count(Channel.id)).where(Channel.enabled == True)
        )
        channel_count = channel_count_result.scalar()

        from app.downloader import get_active_download_counts

        return {
            "total_videos": total_videos,
            "channels": channel_count,
            "downloads": {
                "completed": completed,
                "pending": pending,
                "downloading": downloading,
                "errors": errors,
                "today": today_downloaded,
            },
            "uploads": {
                "uploaded": uploaded,
                "pending": upload_pending,
                "errors": upload_errors,
                "today": today_uploaded,
            },
            "total_size_mb": round(total_size / 1024 / 1024, 1) if total_size else 0,
            "sync": get_sync_status(),
            "active": get_active_download_counts(),
        }
