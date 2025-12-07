# Tube Sync

[![Build Test](https://github.com/capynet/tubesync/actions/workflows/build-test.yml/badge.svg)](https://github.com/capynet/tubesync/actions/workflows/build-test.yml)
[![Release](https://github.com/capynet/tubesync/actions/workflows/release.yml/badge.svg)](https://github.com/capynet/tubesync/releases)

Automatic YouTube video downloader with SMB/FTP upload support and desktop GUI.

## Features

- Auto-downloads videos from YouTube subscriptions (via YouTube Data API)
- Parallel downloads (configurable)
- Parallel uploads via SMB or FTP (configurable)
- Separates Shorts (<=60s) into dedicated folder
- Manual subtitles download (Spanish/English) embedded in MP4
- Desktop GUI application (GTK4/Libadwaita)
- SMB/FTP configuration via GUI
- Skips live streams automatically
- YouTube API quota management with automatic backoff

## Install

### APT Repository (Recommended)

Add the Capynet APT repository and install with `apt`:

```bash
# Add GPG key
curl -fsSL https://capynet.github.io/tubesync/capynet-apt.gpg | sudo gpg --dearmor -o /usr/share/keyrings/capynet.gpg

# Add repository
echo "deb [signed-by=/usr/share/keyrings/capynet.gpg] https://capynet.github.io/tubesync stable main" | sudo tee /etc/apt/sources.list.d/capynet.list

# Install
sudo apt update
sudo apt install tubesync
```

Updates are automatically available via `apt upgrade`.

### Download .deb from GitHub Releases

Download the latest `.deb` from [Releases](https://github.com/capynet/tubesync/releases) and install:

```bash
wget https://github.com/capynet/tubesync/releases/latest/download/tubesync_0.1.0_amd64.deb
sudo dpkg -i tubesync_*.deb
sudo apt-get install -f  # Install dependencies if needed
```

## Usage

```bash
# Launch desktop GUI
tubesync-gui
```

Or find "Tube Sync" in your applications menu.

## YouTube API Setup (optional)

Required for automatic subscription downloads:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable YouTube Data API v3
3. Create OAuth 2.0 credentials (Desktop app)
4. Download as `google-client.json` to `~/.config/tubesync/`
5. Run OAuth setup from the app directory:
   ```bash
   python3 oauth_setup.py
   ```
6. Authorize in browser -> `youtube_token.json` will be created

## Configuration

All settings are configurable through the GUI. Configuration is stored in `~/.config/tubesync/config.json`.

| Setting | Description | Default |
|---------|-------------|---------|
| `download_dir` | Download directory | ~/.local/share/tubesync/downloads |
| `video_quality` | Video quality (best, 1080p, 720p, 480p) | best |
| `max_concurrent_downloads` | Parallel video downloads | 3 |
| `max_concurrent_shorts_downloads` | Parallel shorts downloads | 3 |
| `smb_enabled` | Enable SMB upload | false |
| `smb_host` | SMB server IP address | - |
| `smb_share` | SMB share name | - |
| `smb_user` | SMB username | - |
| `smb_password` | SMB password | - |
| `smb_path` | Path for videos | /youtube |
| `smb_shorts_path` | Path for shorts | /shorts |
| `ftp_enabled` | Enable FTP upload | false |
| `ftp_host` | FTP server address | - |
| `ftp_port` | FTP port | 21 |
| `ftp_user` | FTP username | - |
| `ftp_password` | FTP password | - |
| `ftp_path` | FTP path for videos | /youtube |
| `ftp_shorts_path` | FTP path for shorts | /shorts |
| `ftp_use_tls` | Use FTPS (TLS) | false |
| `delete_after_upload` | Delete local after upload | true |
| `shorts_max_duration` | Max duration for shorts (seconds) | 60 |

## Building Packages

### Build .deb (Linux)

```bash
./build-deb.sh [version]

# Example:
./build-deb.sh 1.0.0
# Output: dist/tubesync_1.0.0_amd64.deb
```

## How It Works

1. **Auto-download (every hour)**: Scans your subscriptions and downloads new videos from the last 5 days
2. **Download**: yt-dlp downloads in best quality with embedded metadata and subtitles
3. **Upload**: Videos are automatically uploaded via SMB or FTP
4. **Shorts Separation**: Videos <=60s go to `/shorts`, the rest to `/youtube`
5. **Cleanup**: Local files are deleted after successful upload (configurable)

## License

MIT
