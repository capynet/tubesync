# TubeSync

[![Build Test](https://github.com/capynet/tubesync/actions/workflows/build-test.yml/badge.svg)](https://github.com/capynet/tubesync/actions/workflows/build-test.yml)
[![Release](https://github.com/capynet/tubesync/actions/workflows/release.yml/badge.svg)](https://github.com/capynet/tubesync/releases)

Web-based YouTube subscription downloader with automatic SMB upload support.

## Features

- Web UI accessible from any browser
- Auto-downloads videos from YouTube subscriptions (via YouTube Data API)
- Parallel downloads (configurable workers)
- Parallel uploads via SMB
- Separates Shorts (<=60s) into dedicated folder
- Skips live streams automatically
- YouTube API quota management with automatic backoff
- Runs as a systemd service

## Install

### APT Repository (Recommended)

Add the Capynet APT repository and install with `apt`:

```bash
# Add GPG key
curl -fsSL https://capynet.github.io/tubesync/capynet-apt.gpg | sudo gpg --dearmor -o /usr/share/keyrings/tubesync.gpg

# Add repository
echo "deb [signed-by=/usr/share/keyrings/tubesync.gpg] https://capynet.github.io/tubesync stable main" | sudo tee /etc/apt/sources.list.d/tubesync.list

# Install
sudo apt update
sudo apt install tubesync
```

Updates are automatically available via `apt upgrade`.

### Download .deb from GitHub Releases

Download the latest `.deb` from [Releases](https://github.com/capynet/tubesync/releases) and install:

```bash
sudo dpkg -i tubesync_*.deb
sudo apt-get install -f  # Install dependencies if needed
```

## Usage

After installation, TubeSync runs as a systemd service and is accessible at:

```
http://localhost:9876
```

Or find "TubeSync" in your applications menu.

### Service Management

```bash
# Check status
sudo systemctl status tubesync

# Stop/Start/Restart
sudo systemctl stop tubesync
sudo systemctl start tubesync
sudo systemctl restart tubesync

# View logs
sudo journalctl -u tubesync -f
```

## First-Time Setup

1. Open http://localhost:9876
2. Go to **Settings** and configure your SMB server
3. Go to **Settings** and upload your Google API credentials (see below)
4. Return to **Dashboard** and click "Authorize with Google"
5. Done! Videos sync automatically every hour

## YouTube API Setup

Required for automatic subscription downloads:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable YouTube Data API v3
3. Create OAuth 2.0 credentials (Web application type)
4. Add authorized redirect URI: `http://localhost:9876/api/youtube/oauth/callback`
5. Download the JSON file
6. Upload it in TubeSync Settings

## Configuration

All settings are configurable through the web UI at http://localhost:9876/settings.

| Setting | Description | Default |
|---------|-------------|---------|
| `download_dir` | Download directory | /var/lib/tubesync/downloads |
| `video_quality` | Video quality (best, 1080p, 720p, 480p) | best |
| `max_concurrent_downloads` | Parallel video downloads | 10 |
| `max_concurrent_shorts_downloads` | Parallel shorts downloads | 10 |
| `smb_enabled` | Enable SMB upload | false |
| `smb_host` | SMB server IP address | - |
| `smb_share` | SMB share name | - |
| `smb_user` | SMB username | - |
| `smb_password` | SMB password | - |
| `smb_path` | Path for videos | /youtube |
| `smb_shorts_path` | Path for shorts | /shorts |
| `delete_after_upload` | Delete local after upload | true |
| `shorts_max_duration` | Max duration for shorts (seconds) | 60 |
| `sync_days_back` | Days to look back for videos | 5 |

## Building from Source

### Build .deb Package

```bash
./build-deb.sh [version]

# Example:
./build-deb.sh 1.0.0
# Output: dist/tubesync_1.0.0_amd64.deb
```

### Development

```bash
# Start development servers (backend + frontend with hot reload)
./run-dev.sh
```

## Architecture

- **Backend**: FastAPI + Uvicorn + SQLAlchemy
- **Frontend**: Vue 3 + Vite + Naive UI
- **Storage**: SMB (smbprotocol)
- **YouTube**: google-api-python-client + OAuth2

## How It Works

1. **Auto-sync (every hour)**: Scans your YouTube subscriptions and queues new videos
2. **Download**: yt-dlp downloads in best quality with embedded metadata
3. **Upload**: Videos are automatically uploaded via SMB
4. **Shorts Separation**: Videos <=60s go to `/shorts`, the rest to `/youtube`
5. **Cleanup**: Local files are deleted after successful upload (configurable)

## License

MIT
