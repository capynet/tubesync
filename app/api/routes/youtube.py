"""YouTube API routes - simplified for automatic sync."""

import json
import logging
import os
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional

from app.auto_download import run_sync, get_sync_status
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Store OAuth state temporarily (in production, use a proper session store)
_oauth_states: dict[str, bool] = {}


class YouTubeStatus(BaseModel):
    configured: bool
    client_file_exists: bool = False
    credentials_valid: bool
    quota_used: int
    quota_limit: int
    quota_exceeded: bool
    quota_reset_time: Optional[str] = None
    error: Optional[str] = None


class ChannelResult(BaseModel):
    channel_name: str
    videos_found: int


class SyncStatus(BaseModel):
    running: bool
    last_sync: Optional[str] = None
    last_queued: int
    channel_count: int
    progress_current: int = 0
    progress_total: int = 0
    channel_results: list[ChannelResult] = []
    total_videos_found: int = 0
    channels_with_videos: int = 0


class SyncResponse(BaseModel):
    success: bool
    videos_queued: int
    message: str


@router.get("/status", response_model=YouTubeStatus)
async def get_youtube_status():
    """Get YouTube API connection status and quota info."""
    try:
        from app.youtube_api import get_api_status

        status = get_api_status()

        return YouTubeStatus(
            configured=status.get('configured', False),
            client_file_exists=status.get('client_file_exists', False),
            credentials_valid=status.get('credentials_valid', False),
            quota_used=status.get('quota_used', 0),
            quota_limit=status.get('quota_limit', 10000),
            quota_exceeded=status.get('quota_exceeded', False),
            quota_reset_time=status.get('quota_reset_time'),
            error=status.get('error')
        )
    except Exception as e:
        logger.error(f"Error getting YouTube status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync-status", response_model=SyncStatus)
async def get_sync_status_endpoint():
    """Get current sync status including progress and channel results."""
    status = get_sync_status()
    return SyncStatus(
        running=status['running'],
        last_sync=status['last_sync'],
        last_queued=status['last_queued'],
        channel_count=status['channel_count'],
        progress_current=status.get('progress_current', 0),
        progress_total=status.get('progress_total', 0),
        channel_results=[
            ChannelResult(channel_name=ch['channel_name'], videos_found=ch['videos_found'])
            for ch in status.get('channel_results', [])
        ],
        total_videos_found=status.get('total_videos_found', 0),
        channels_with_videos=status.get('channels_with_videos', 0),
    )


@router.post("/sync", response_model=SyncResponse)
async def trigger_sync():
    """Trigger manual sync (useful for testing, normally automatic)."""
    try:
        from app.youtube_api import is_api_configured

        if not is_api_configured():
            raise HTTPException(status_code=400, detail="YouTube API not configured")

        queued = await run_sync()

        return SyncResponse(
            success=True,
            videos_queued=queued,
            message=f"Sync completed. {queued} videos queued."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class OAuthStartResponse(BaseModel):
    auth_url: str


@router.post("/oauth/start", response_model=OAuthStartResponse)
async def start_oauth():
    """Start OAuth flow - returns URL for user to authorize."""
    try:
        from app.youtube_api import start_oauth_flow, get_api_status

        status = get_api_status()
        if not status.get('client_file_exists'):
            raise HTTPException(
                status_code=400,
                detail="Google API client file not configured. Please add google-client.json first."
            )

        auth_url, state = start_oauth_flow()
        _oauth_states[state] = True

        return OAuthStartResponse(auth_url=auth_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting OAuth: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/oauth/callback")
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    """OAuth callback - Google redirects here after user authorizes."""
    if error:
        return HTMLResponse(content=f"""
            <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>Authorization Failed</h1>
                <p>Error: {error}</p>
                <p><a href="/">Return to TubeSync</a></p>
            </body>
            </html>
        """, status_code=400)

    if not code or not state:
        return HTMLResponse(content="""
            <html>
            <head><title>Invalid Request</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>Invalid Request</h1>
                <p>Missing authorization code or state.</p>
                <p><a href="/">Return to TubeSync</a></p>
            </body>
            </html>
        """, status_code=400)

    # Verify state to prevent CSRF
    if state not in _oauth_states:
        return HTMLResponse(content="""
            <html>
            <head><title>Invalid State</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>Invalid State</h1>
                <p>The authorization request has expired or is invalid. Please try again.</p>
                <p><a href="/">Return to TubeSync</a></p>
            </body>
            </html>
        """, status_code=400)

    try:
        from app.youtube_api import complete_oauth_flow

        # Remove state (one-time use)
        del _oauth_states[state]

        # Complete the OAuth flow
        complete_oauth_flow(code, state)

        # Return success page that closes the popup
        return HTMLResponse(content="""
            <html>
            <head>
                <title>Authorization Successful</title>
                <script>
                    // Close this popup after 2 seconds
                    setTimeout(function() {
                        window.close();
                    }, 2000);
                </script>
            </head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1 style="color: #4CAF50;">&#10004; Authorization Successful!</h1>
                <p>TubeSync is now connected to your YouTube account.</p>
                <p style="color: #888;">This window will close automatically...</p>
            </body>
            </html>
        """)
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return HTMLResponse(content=f"""
            <html>
            <head><title>Authorization Error</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>Authorization Error</h1>
                <p>An error occurred while completing authorization: {str(e)}</p>
                <p><a href="/">Return to TubeSync</a></p>
            </body>
            </html>
        """, status_code=500)


class UploadCredentialsResponse(BaseModel):
    success: bool
    message: str


@router.post("/credentials/upload", response_model=UploadCredentialsResponse)
async def upload_credentials(file: UploadFile = File(...)):
    """Upload Google API client credentials file (google-client.json)."""
    try:
        # Read file content
        content = await file.read()

        # Validate it's valid JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")

        # Validate it looks like a Google OAuth client file
        # It should have either "installed" or "web" key with client_id and client_secret
        if "installed" in data:
            client_info = data["installed"]
        elif "web" in data:
            client_info = data["web"]
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid credentials file. Expected Google OAuth client JSON with 'installed' or 'web' configuration."
            )

        if "client_id" not in client_info or "client_secret" not in client_info:
            raise HTTPException(
                status_code=400,
                detail="Invalid credentials file. Missing client_id or client_secret."
            )

        # Ensure directory exists
        client_file = settings.youtube_client_file
        os.makedirs(os.path.dirname(client_file), exist_ok=True)

        # Save the file
        with open(client_file, 'wb') as f:
            f.write(content)

        logger.info(f"Google client credentials uploaded to {client_file}")

        return UploadCredentialsResponse(
            success=True,
            message="Credentials uploaded successfully. You can now authorize with Google."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/credentials")
async def delete_credentials():
    """Delete Google API credentials (both client file and token)."""
    try:
        deleted = []

        # Delete client file
        client_file = settings.youtube_client_file
        if os.path.exists(client_file):
            os.remove(client_file)
            deleted.append("client credentials")

        # Delete token file
        token_file = settings.youtube_token_file
        if os.path.exists(token_file):
            os.remove(token_file)
            deleted.append("authorization token")

        if deleted:
            return {"success": True, "message": f"Deleted: {', '.join(deleted)}"}
        else:
            return {"success": True, "message": "No credentials to delete"}

    except Exception as e:
        logger.error(f"Error deleting credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))
