import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime

from sqlalchemy import select, func, desc
from app.database import async_session
from app.models import Video
from app.downloader import get_download_progress, is_downloads_paused, pause_downloads, resume_downloads
from app.auto_download import get_stats

logger = logging.getLogger(__name__)
router = APIRouter()


class VideoResponse(BaseModel):
    id: int
    youtube_id: str
    title: str
    channel: str
    duration: int
    thumbnail: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    downloaded_at: Optional[datetime] = None
    upload_status: str
    uploaded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class VideoListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    videos: List[VideoResponse]


class DownloadProgress(BaseModel):
    worker_id: int
    video_id: int
    title: str
    status: str
    percent: float
    speed: float
    eta: int


@router.get("", response_model=VideoListResponse)
async def list_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status")
):
    """List all videos with pagination."""
    async with async_session() as session:
        # Build query
        query = select(Video)
        count_query = select(func.count(Video.id))

        if status:
            query = query.where(Video.status == status)
            count_query = count_query.where(Video.status == status)

        # Get total count
        total_result = await session.execute(count_query)
        total = total_result.scalar()

        # Get paginated results
        offset = (page - 1) * page_size
        query = query.order_by(desc(Video.created_at)).offset(offset).limit(page_size)
        result = await session.execute(query)
        videos = result.scalars().all()

        return VideoListResponse(
            total=total,
            page=page,
            page_size=page_size,
            videos=[VideoResponse.model_validate(v) for v in videos]
        )


@router.get("/stats")
async def get_download_stats():
    """Get download and upload statistics."""
    try:
        stats = await get_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/progress")
async def get_progress():
    """Get progress of active downloads."""
    progress = get_download_progress()
    return {"active_downloads": progress}


@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(video_id: int):
    """Get details of a specific video."""
    async with async_session() as session:
        result = await session.execute(
            select(Video).where(Video.id == video_id)
        )
        video = result.scalar_one_or_none()

        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        return VideoResponse.model_validate(video)


@router.delete("/{video_id}")
async def delete_video(video_id: int):
    """Delete a video record."""
    async with async_session() as session:
        result = await session.execute(
            select(Video).where(Video.id == video_id)
        )
        video = result.scalar_one_or_none()

        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        await session.delete(video)
        await session.commit()

        return {"success": True, "message": "Video deleted"}


@router.get("/pause/status")
async def get_pause_status():
    """Get whether downloads are paused."""
    return {"paused": is_downloads_paused()}


@router.post("/pause")
async def pause_all_downloads():
    """Pause all downloads. Current downloads will finish but new ones won't start."""
    pause_downloads()
    return {"success": True, "paused": True, "message": "Downloads paused"}


@router.post("/resume")
async def resume_all_downloads():
    """Resume all downloads."""
    resume_downloads()
    return {"success": True, "paused": False, "message": "Downloads resumed"}
