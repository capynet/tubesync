"""
YouTube API module - Fetches subscriptions and videos using OAuth2.
Simplified version - automatic sync only, no manual preview.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

logger = logging.getLogger(__name__)

# Silence googleapiclient file_cache warning
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

# Paths for credentials (from settings)
TOKEN_FILE = settings.youtube_token_file
CLIENT_SECRETS_FILE = settings.youtube_client_file

# Cache for YouTube service
_youtube_service = None
_credentials = None

# Quota management
_quota_exceeded = False
_quota_reset_time = None
_quota_used_today = 0
_quota_date = None
_quota_loaded = False
DAILY_QUOTA_LIMIT = 10000


def _load_quota_state():
    """Load quota state from database."""
    global _quota_used_today, _quota_date, _quota_exceeded, _quota_reset_time, _quota_loaded

    if _quota_loaded:
        return

    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from app.config import DATA_DIR
        from app.models import AppState

        db_path = DATA_DIR / "data" / "videos.db"
        if not db_path.exists():
            _quota_loaded = True
            return

        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            result = session.execute(select(AppState).where(AppState.key == "youtube_quota"))
            state = result.scalar_one_or_none()

            if state:
                data = json.loads(state.value)
                saved_date = data.get('date')
                today = datetime.utcnow().date().isoformat()

                if saved_date == today:
                    _quota_used_today = data.get('used', 0)
                    _quota_date = datetime.utcnow().date()
                    _quota_exceeded = data.get('exceeded', False)
                    if data.get('reset_time'):
                        _quota_reset_time = datetime.fromisoformat(data['reset_time'])
                else:
                    _quota_used_today = 0
                    _quota_date = datetime.utcnow().date()
                    _quota_exceeded = False
                    _quota_reset_time = None

        _quota_loaded = True
    except Exception as e:
        logger.debug(f"Could not load quota state: {e}")
        _quota_loaded = True


def _save_quota_state():
    """Save quota state to database."""
    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from app.config import DATA_DIR
        from app.models import AppState

        db_path = DATA_DIR / "data" / "videos.db"
        if not db_path.exists():
            return

        data = {
            'date': datetime.utcnow().date().isoformat(),
            'used': _quota_used_today,
            'exceeded': _quota_exceeded,
            'reset_time': _quota_reset_time.isoformat() if _quota_reset_time else None,
        }

        engine = create_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            result = session.execute(select(AppState).where(AppState.key == "youtube_quota"))
            state = result.scalar_one_or_none()

            if state:
                state.value = json.dumps(data)
            else:
                state = AppState(key="youtube_quota", value=json.dumps(data))
                session.add(state)

            session.commit()
    except Exception as e:
        logger.error(f"Error saving quota state: {e}")


def mark_quota_exceeded():
    """Mark quota as exceeded and calculate reset time."""
    global _quota_exceeded, _quota_reset_time
    from datetime import timezone
    import pytz

    _quota_exceeded = True
    pt = pytz.timezone('America/Los_Angeles')
    now_pt = datetime.now(pt)
    tomorrow_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    _quota_reset_time = tomorrow_pt.astimezone(timezone.utc).replace(tzinfo=None)

    _save_quota_state()
    logger.warning(f"YouTube API quota exceeded. Will retry after {tomorrow_pt.strftime('%Y-%m-%d %H:%M %Z')}")


def is_quota_exceeded() -> bool:
    """Check if quota is exceeded."""
    global _quota_exceeded, _quota_reset_time

    if not _quota_exceeded:
        return False

    if _quota_reset_time and datetime.utcnow() > _quota_reset_time:
        logger.info("YouTube API quota reset")
        _quota_exceeded = False
        _quota_reset_time = None
        return False

    return True


def get_quota_status() -> dict:
    """Get quota status for display."""
    return {
        'exceeded': _quota_exceeded,
        'reset_time': _quota_reset_time.isoformat() if _quota_reset_time else None,
        'used': _quota_used_today,
        'limit': DAILY_QUOTA_LIMIT,
    }


def _reset_quota_if_new_day():
    """Reset quota counter if it's a new day."""
    global _quota_used_today, _quota_date, _quota_exceeded
    today = datetime.utcnow().date()
    if _quota_date != today:
        _quota_used_today = 0
        _quota_date = today
        if _quota_exceeded and _quota_reset_time and datetime.utcnow() > _quota_reset_time:
            _quota_exceeded = False
            _quota_reset_time = None


def add_quota_usage(units: int):
    """Add to quota usage counter."""
    global _quota_used_today
    _reset_quota_if_new_day()
    _quota_used_today += units
    _save_quota_state()


def get_quota_usage() -> tuple[int, int]:
    """Get current quota usage (used, limit)."""
    _load_quota_state()
    _reset_quota_if_new_day()
    return _quota_used_today, DAILY_QUOTA_LIMIT


def get_credentials() -> Optional[Credentials]:
    """Load and refresh credentials from token file."""
    global _credentials

    if _credentials is not None and _credentials.valid:
        return _credentials

    if not os.path.exists(TOKEN_FILE):
        logger.error(f"Token file not found: {TOKEN_FILE}")
        return None

    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)

        _credentials = Credentials(
            token=token_data.get('token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri'),
            client_id=token_data.get('client_id'),
            client_secret=token_data.get('client_secret'),
            scopes=token_data.get('scopes')
        )

        if not _credentials.valid and _credentials.refresh_token:
            logger.info("Refreshing credentials...")
            _credentials.refresh(Request())
            token_data['token'] = _credentials.token
            with open(TOKEN_FILE, 'w') as f:
                json.dump(token_data, f, indent=2)

        return _credentials

    except Exception as e:
        logger.error(f"Error loading credentials: {e}")
        return None


def get_youtube_service():
    """Get authenticated YouTube API service."""
    global _youtube_service

    credentials = get_credentials()
    if not credentials:
        return None

    try:
        _youtube_service = build('youtube', 'v3', credentials=credentials)
        return _youtube_service
    except Exception as e:
        logger.error(f"Error building YouTube service: {e}")
        return None


def get_subscriptions() -> list[dict]:
    """Get all subscribed channels."""
    if is_quota_exceeded():
        logger.warning("Skipping get_subscriptions - quota exceeded")
        return []

    youtube = get_youtube_service()
    if not youtube:
        return []

    subscriptions = []
    next_page_token = None

    try:
        while True:
            request = youtube.subscriptions().list(
                part='snippet',
                mine=True,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()
            add_quota_usage(1)

            for item in response.get('items', []):
                snippet = item.get('snippet', {})
                resource = snippet.get('resourceId', {})

                subscriptions.append({
                    'channel_id': resource.get('channelId'),
                    'channel_title': snippet.get('title'),
                    'thumbnail': snippet.get('thumbnails', {}).get('default', {}).get('url', ''),
                })

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

        logger.info(f"Found {len(subscriptions)} subscriptions")
        return subscriptions

    except HttpError as e:
        if e.resp.status == 403 and 'quotaExceeded' in str(e):
            mark_quota_exceeded()
        else:
            logger.error(f"YouTube API error: {e}")
        return []


def get_channel_uploads_playlist(channel_id: str) -> Optional[str]:
    """Get the uploads playlist ID for a channel."""
    youtube = get_youtube_service()
    if not youtube:
        return None

    try:
        request = youtube.channels().list(
            part='contentDetails',
            id=channel_id
        )
        response = request.execute()
        add_quota_usage(1)

        items = response.get('items', [])
        if items:
            return items[0]['contentDetails']['relatedPlaylists']['uploads']
        return None

    except HttpError as e:
        logger.error(f"Error getting uploads playlist for {channel_id}: {e}")
        return None


def get_recent_videos_from_channel(channel_id: str, max_results: int = 10,
                                    stop_at_video_id: Optional[str] = None,
                                    published_after: Optional[datetime] = None) -> list[dict]:
    """
    Get recent videos from a channel.

    Args:
        channel_id: YouTube channel ID
        max_results: Maximum videos to return
        stop_at_video_id: Stop when reaching this video ID (already processed)
        published_after: Only return videos published after this date

    Returns list of video dicts, newest first.
    """
    youtube = get_youtube_service()
    if not youtube:
        return []

    uploads_playlist_id = get_channel_uploads_playlist(channel_id)
    if not uploads_playlist_id:
        return []

    videos = []

    try:
        request = youtube.playlistItems().list(
            part='snippet,contentDetails',
            playlistId=uploads_playlist_id,
            maxResults=max_results
        )
        response = request.execute()
        add_quota_usage(1)

        for item in response.get('items', []):
            snippet = item.get('snippet', {})
            content_details = item.get('contentDetails', {})
            video_id = content_details.get('videoId')

            if not video_id:
                continue

            # Stop if we reach a video we've already seen
            if stop_at_video_id and video_id == stop_at_video_id:
                break

            published_at_str = snippet.get('publishedAt', '')
            try:
                published_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
                published_at = published_at.replace(tzinfo=None)
            except:
                published_at = datetime.utcnow()

            # Skip videos older than published_after
            if published_after and published_at < published_after:
                continue

            videos.append({
                'youtube_id': video_id,
                'title': snippet.get('title', 'Unknown'),
                'channel': snippet.get('channelTitle', 'Unknown'),
                'channel_id': snippet.get('channelId', channel_id),
                'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                'published_at': published_at,
                'duration': 0,
            })

        return videos

    except HttpError as e:
        if e.resp.status == 403 and 'quotaExceeded' in str(e):
            mark_quota_exceeded()
        else:
            logger.error(f"Error getting videos from channel {channel_id}: {e}")
        return []


def get_video_details(video_ids: list[str]) -> dict[str, dict]:
    """Get detailed info for videos (duration, etc)."""
    youtube = get_youtube_service()
    if not youtube or not video_ids:
        return {}

    details = {}

    try:
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]

            request = youtube.videos().list(
                part='contentDetails,snippet',
                id=','.join(batch)
            )
            response = request.execute()
            add_quota_usage(1)

            for item in response.get('items', []):
                video_id = item['id']
                content_details = item.get('contentDetails', {})
                snippet = item.get('snippet', {})

                duration_str = content_details.get('duration', 'PT0S')
                duration_seconds = parse_duration(duration_str)

                live_status = snippet.get('liveBroadcastContent', 'none')
                is_live = live_status in ('live', 'upcoming')

                thumbnails = snippet.get('thumbnails', {})
                thumbnail_url = (thumbnails.get('medium', {}).get('url') or
                                thumbnails.get('default', {}).get('url', ''))

                details[video_id] = {
                    'duration': duration_seconds,
                    'is_live': is_live,
                    'title': snippet.get('title', 'Unknown'),
                    'channel': snippet.get('channelTitle', 'Unknown'),
                    'thumbnail': thumbnail_url,
                }

        return details

    except HttpError as e:
        if e.resp.status == 403 and 'quotaExceeded' in str(e):
            mark_quota_exceeded()
        else:
            logger.error(f"Error getting video details: {e}")
        return {}


def parse_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration (PT4M13S) to seconds."""
    import re
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def is_api_configured() -> bool:
    """Check if YouTube API is properly configured."""
    return os.path.exists(TOKEN_FILE)


def get_api_status() -> dict:
    """Get status of YouTube API configuration."""
    quota_status = get_quota_status()

    status = {
        'configured': os.path.exists(CLIENT_SECRETS_FILE),
        'token_file_exists': os.path.exists(TOKEN_FILE),
        'client_file_exists': os.path.exists(CLIENT_SECRETS_FILE),
        'credentials_valid': False,
        'quota_exceeded': quota_status['exceeded'],
        'quota_reset_time': quota_status['reset_time'],
        'quota_used': quota_status['used'],
        'quota_limit': quota_status['limit'],
    }

    if not status['client_file_exists']:
        status['error'] = 'Google API client file not found. Download from Google Cloud Console.'
        return status

    if not status['token_file_exists']:
        status['error'] = 'Not authorized. Click "Authorize with Google" to connect your account.'
        return status

    credentials = get_credentials()
    if credentials:
        status['credentials_valid'] = True
    else:
        status['error'] = 'Authorization expired. Click "Authorize with Google" to reconnect.'

    return status


def start_oauth_flow() -> tuple[str, str]:
    """
    Start OAuth flow and return (auth_url, state).
    The state should be stored and verified in the callback.
    """
    from google_auth_oauthlib.flow import Flow
    import secrets

    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise ValueError("Google API client file not found")

    # Generate a random state for CSRF protection
    state = secrets.token_urlsafe(32)

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=['https://www.googleapis.com/auth/youtube.readonly'],
        state=state
    )

    # For local development, use localhost callback
    # In production, this should match the configured redirect URI
    flow.redirect_uri = 'http://localhost:9876/api/youtube/oauth/callback'

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    return auth_url, state


def complete_oauth_flow(code: str, state: str) -> bool:
    """
    Complete OAuth flow with the authorization code.
    Returns True if successful.
    """
    from google_auth_oauthlib.flow import Flow
    global _credentials, _youtube_service

    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise ValueError("Google API client file not found")

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=['https://www.googleapis.com/auth/youtube.readonly'],
        state=state
    )
    flow.redirect_uri = 'http://localhost:9876/api/youtube/oauth/callback'

    # Exchange code for credentials
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # Save credentials to token file
    token_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)

    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f, indent=2)

    # Update cached credentials
    _credentials = credentials
    _youtube_service = None

    logger.info("OAuth flow completed successfully")
    return True
