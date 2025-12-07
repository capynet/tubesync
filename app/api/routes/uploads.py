import logging
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.smb_upload import (
    get_upload_progress, get_upload_stats, test_smb_connection as sync_test_smb,
    pause_uploads, resume_uploads, is_paused
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SMBStatus(BaseModel):
    enabled: bool
    connected: bool
    host: str
    share: str
    error: Optional[str] = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


class TestConnectionRequest(BaseModel):
    """Optional credentials to test with (uses form values instead of saved config)."""
    host: Optional[str] = None
    share: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    path: Optional[str] = None


def test_smb_with_credentials(host: str, share: str, user: str, password: str, path: str) -> tuple[bool, str]:
    """Test SMB connection with specific credentials."""
    from smbclient import register_session, stat

    if not host or not user:
        return False, "NOT CONFIGURED"

    try:
        register_session(host, username=user, password=password)

        # Build path to test
        remote_path = path.strip("/") if path else ""
        if remote_path:
            smb_dir = f"\\\\{host}\\{share}\\{remote_path}"
        else:
            smb_dir = f"\\\\{host}\\{share}"

        stat(smb_dir)
        return True, "OK"
    except Exception as e:
        error_msg = str(e)
        if "STATUS_LOGON_FAILURE" in error_msg:
            return False, "AUTH FAILED"
        elif "timed out" in error_msg.lower() or "unreachable" in error_msg.lower():
            return False, "UNREACHABLE"
        elif "STATUS_BAD_NETWORK_NAME" in error_msg:
            return False, "SHARE NOT FOUND"
        else:
            logger.error(f"SMB connection test failed: {e}")
            return False, "ERROR"


@router.get("/status", response_model=SMBStatus)
async def get_upload_status():
    """Get SMB connection status."""
    from app.config import settings

    if not settings.smb_enabled:
        return SMBStatus(
            enabled=False,
            connected=False,
            host="",
            share=""
        )

    # Try to test connection (run in executor since it's blocking)
    try:
        loop = asyncio.get_event_loop()
        success, message = await loop.run_in_executor(None, sync_test_smb)
        return SMBStatus(
            enabled=True,
            connected=success,
            host=settings.smb_host,
            share=settings.smb_share,
            error=None if success else message
        )
    except Exception as e:
        return SMBStatus(
            enabled=True,
            connected=False,
            host=settings.smb_host,
            share=settings.smb_share,
            error=str(e)
        )


@router.post("/test", response_model=TestConnectionResponse)
async def test_connection(request: TestConnectionRequest = None):
    """Test SMB connection with form values or saved settings."""
    from app.config import settings

    # Use request values if provided, otherwise fall back to saved settings
    host = request.host if request and request.host else settings.smb_host
    share = request.share if request and request.share else settings.smb_share
    user = request.user if request and request.user else settings.smb_user
    password = request.password if request and request.password is not None else settings.smb_password
    path = request.path if request and request.path else settings.smb_path

    if not host or not share:
        raise HTTPException(status_code=400, detail="SMB host and share must be configured")

    try:
        loop = asyncio.get_event_loop()
        success, message = await loop.run_in_executor(
            None, test_smb_with_credentials, host, share, user, password, path
        )
        return TestConnectionResponse(
            success=success,
            message=message
        )
    except Exception as e:
        logger.error(f"Error testing SMB connection: {e}")
        return TestConnectionResponse(
            success=False,
            message=str(e)
        )


@router.get("/progress")
async def get_progress():
    """Get progress of active uploads."""
    progress = get_upload_progress()
    stats = get_upload_stats()
    stats["paused"] = is_paused()
    return {
        "active_uploads": progress,
        "stats": stats
    }


@router.get("/pause/status")
async def get_pause_status():
    """Get upload pause status."""
    return {"paused": is_paused()}


@router.post("/pause")
async def pause_upload_queue():
    """Pause SMB uploads (current uploads will finish, new ones won't start)."""
    pause_uploads()
    return {"paused": True, "message": "Uploads paused"}


@router.post("/resume")
async def resume_upload_queue():
    """Resume SMB uploads."""
    resume_uploads()
    return {"paused": False, "message": "Uploads resumed"}
