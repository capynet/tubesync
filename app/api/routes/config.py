import logging
import subprocess
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import load_config, save_config, settings

logger = logging.getLogger(__name__)
router = APIRouter()

SERVICE_NAME = "tubesync"


class ConfigResponse(BaseModel):
    download_dir: str
    video_quality: str
    max_concurrent_downloads: int
    max_concurrent_shorts_downloads: int
    smb_enabled: bool
    smb_host: str
    smb_share: str
    smb_user: str
    smb_path: str
    smb_shorts_path: str
    max_concurrent_smb_uploads: int
    delete_after_upload: bool
    shorts_max_duration: int
    auto_download_enabled: bool
    sync_days_back: int


class ConfigUpdate(BaseModel):
    download_dir: Optional[str] = None
    video_quality: Optional[str] = None
    max_concurrent_downloads: Optional[int] = None
    max_concurrent_shorts_downloads: Optional[int] = None
    smb_enabled: Optional[bool] = None
    smb_host: Optional[str] = None
    smb_share: Optional[str] = None
    smb_user: Optional[str] = None
    smb_password: Optional[str] = None
    smb_path: Optional[str] = None
    smb_shorts_path: Optional[str] = None
    max_concurrent_smb_uploads: Optional[int] = None
    delete_after_upload: Optional[bool] = None
    shorts_max_duration: Optional[int] = None
    auto_download_enabled: Optional[bool] = None
    sync_days_back: Optional[int] = None


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Get current configuration (excluding sensitive data like passwords)."""
    return ConfigResponse(
        download_dir=settings.download_dir,
        video_quality=settings.video_quality,
        max_concurrent_downloads=settings.max_concurrent_downloads,
        max_concurrent_shorts_downloads=settings.max_concurrent_shorts_downloads,
        smb_enabled=settings.smb_enabled,
        smb_host=settings.smb_host,
        smb_share=settings.smb_share,
        smb_user=settings.smb_user,
        smb_path=settings.smb_path,
        smb_shorts_path=settings.smb_shorts_path,
        max_concurrent_smb_uploads=settings.max_concurrent_smb_uploads,
        delete_after_upload=settings.delete_after_upload,
        shorts_max_duration=settings.shorts_max_duration,
        auto_download_enabled=settings.auto_download_enabled,
        sync_days_back=settings.sync_days_back,
    )


@router.put("")
async def update_config(config_update: ConfigUpdate):
    """Update configuration."""
    try:
        # Load current config
        current = load_config()

        # Update only provided fields
        update_data = config_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                current[key] = value

        # Save config
        save_config(current)

        # Reload settings
        settings.reload()

        return {"success": True, "message": "Configuration updated"}
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AutostartStatus(BaseModel):
    enabled: bool
    available: bool  # True if systemd service exists


@router.get("/autostart")
async def get_autostart_status():
    """Check if TubeSync is enabled to start on boot."""
    try:
        # Check if service exists
        result = subprocess.run(
            ["systemctl", "list-unit-files", f"{SERVICE_NAME}.service"],
            capture_output=True, text=True
        )
        available = SERVICE_NAME in result.stdout

        if not available:
            return AutostartStatus(enabled=False, available=False)

        # Check if enabled
        result = subprocess.run(
            ["systemctl", "is-enabled", SERVICE_NAME],
            capture_output=True, text=True
        )
        enabled = result.returncode == 0

        return AutostartStatus(enabled=enabled, available=True)
    except Exception as e:
        logger.error(f"Error checking autostart status: {e}")
        return AutostartStatus(enabled=False, available=False)


@router.post("/autostart/enable")
async def enable_autostart():
    """Enable TubeSync to start on boot."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "enable", SERVICE_NAME],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr or "Failed to enable autostart")
        return {"success": True, "enabled": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling autostart: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/autostart/disable")
async def disable_autostart():
    """Disable TubeSync from starting on boot."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "disable", SERVICE_NAME],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr or "Failed to disable autostart")
        return {"success": True, "enabled": False}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling autostart: {e}")
        raise HTTPException(status_code=500, detail=str(e))
