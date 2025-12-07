#!/bin/bash
# Build .deb package for TubeSync (Web Service)
# Usage: ./build-deb.sh [version]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="${VERSION:-${1:-0.0.1}}"
PACKAGE_NAME="tubesync"
ARCH="amd64"
BUILD_DIR="$SCRIPT_DIR/build/deb"
PACKAGE_DIR="$BUILD_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}"
INSTALL_DIR="/opt/tubesync"

echo "==================================="
echo "Building TubeSync .deb package"
echo "Version: $VERSION"
echo "==================================="

# Check dependencies
if ! command -v dpkg-deb &> /dev/null; then
    echo "dpkg-deb not found. Install with: sudo apt install dpkg"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "npm not found. Install Node.js first."
    exit 1
fi

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$PACKAGE_DIR"

# Create directory structure
mkdir -p "$PACKAGE_DIR/DEBIAN"
mkdir -p "$PACKAGE_DIR$INSTALL_DIR/app"
mkdir -p "$PACKAGE_DIR$INSTALL_DIR/frontend/dist"
mkdir -p "$PACKAGE_DIR$INSTALL_DIR/venv"
mkdir -p "$PACKAGE_DIR/usr/local/bin"
mkdir -p "$PACKAGE_DIR/lib/systemd/system"
mkdir -p "$PACKAGE_DIR/usr/share/applications"
mkdir -p "$PACKAGE_DIR/usr/share/icons/hicolor/scalable/apps"

# Build frontend
echo "Building frontend..."
cd "$SCRIPT_DIR/frontend"
npm install --silent
npm run build
cd "$SCRIPT_DIR"

echo "Creating virtual environment for package..."
python3 -m venv "$PACKAGE_DIR$INSTALL_DIR/venv"
source "$PACKAGE_DIR$INSTALL_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
deactivate

# Fix venv shebangs (they point to build directory, need to point to install directory)
echo "Fixing venv shebangs..."
find "$PACKAGE_DIR$INSTALL_DIR/venv/bin" -type f -exec sed -i "1s|^#!.*/build/deb/[^/]*/opt/tubesync/venv/bin/python.*|#!/opt/tubesync/venv/bin/python|" {} \;

# Make venv world-readable
chmod -R a+rX "$PACKAGE_DIR$INSTALL_DIR/venv"

echo "Copying application files..."
# Copy app files
cp -r "$SCRIPT_DIR/app/"* "$PACKAGE_DIR$INSTALL_DIR/app/"
cp "$SCRIPT_DIR/requirements.txt" "$PACKAGE_DIR$INSTALL_DIR/"

# Copy frontend dist
cp -r "$SCRIPT_DIR/frontend/dist/"* "$PACKAGE_DIR$INSTALL_DIR/frontend/dist/"

# Fix permissions on app and frontend (make world-readable)
chmod -R a+rX "$PACKAGE_DIR$INSTALL_DIR/app"
chmod -R a+rX "$PACKAGE_DIR$INSTALL_DIR/frontend"

# Create CLI wrapper script
cat > "$PACKAGE_DIR$INSTALL_DIR/tubesync-server" << 'SCRIPT'
#!/bin/bash
# TubeSync Server - Start the web service
cd /opt/tubesync
exec /opt/tubesync/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9876
SCRIPT
chmod +x "$PACKAGE_DIR$INSTALL_DIR/tubesync-server"

# Create symlink in /usr/local/bin
ln -sf "$INSTALL_DIR/tubesync-server" "$PACKAGE_DIR/usr/local/bin/tubesync-server"
ln -sf "$INSTALL_DIR/tubesync-server" "$PACKAGE_DIR/usr/local/bin/tubesync"

# Install icon
cp "$SCRIPT_DIR/assets/icon.svg" "$PACKAGE_DIR/usr/share/icons/hicolor/scalable/apps/tubesync.svg"

# Create desktop entry
cat > "$PACKAGE_DIR/usr/share/applications/tubesync.desktop" << 'DESKTOP'
[Desktop Entry]
Name=TubeSync
Comment=YouTube Subscription Downloader
Exec=xdg-open http://localhost:9876
Icon=tubesync
Terminal=false
Type=Application
Categories=Network;AudioVideo;
Keywords=youtube;download;video;sync;
DESKTOP

# Create systemd service
cat > "$PACKAGE_DIR/lib/systemd/system/tubesync.service" << 'SERVICE'
[Unit]
Description=TubeSync - YouTube Subscription Downloader
After=network.target

[Service]
Type=simple
User=tubesync
Group=tubesync
WorkingDirectory=/opt/tubesync
ExecStart=/opt/tubesync/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9876
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICE

# Create DEBIAN control file
cat > "$PACKAGE_DIR/DEBIAN/control" << CONTROL
Package: $PACKAGE_NAME
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.10), python3-venv, ffmpeg
Maintainer: Capynet <capynet@users.noreply.github.com>
Description: YouTube Subscription Downloader with SMB Upload
 Web-based YouTube video downloader with automatic SMB upload.
 .
 Features:
  - Auto-downloads videos from YouTube subscriptions
  - Parallel downloads and uploads via SMB
  - Separates Shorts into dedicated folder
  - Web UI accessible from any browser
  - Runs as a systemd service
 .
 Access the web UI at http://localhost:9876 after starting the service.
Homepage: https://github.com/capynet/tubesync
CONTROL

# Create sudoers file for autostart control
mkdir -p "$PACKAGE_DIR/etc/sudoers.d"
cat > "$PACKAGE_DIR/etc/sudoers.d/tubesync" << 'SUDOERS'
# Allow tubesync service to enable/disable itself
tubesync ALL=(ALL) NOPASSWD: /usr/bin/systemctl enable tubesync
tubesync ALL=(ALL) NOPASSWD: /usr/bin/systemctl disable tubesync
SUDOERS
chmod 440 "$PACKAGE_DIR/etc/sudoers.d/tubesync"

# Create postinst script
cat > "$PACKAGE_DIR/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e

# Create tubesync user if doesn't exist
if ! id -u tubesync &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin tubesync
    echo "Created system user: tubesync"
fi

# Create data directories with proper ownership
mkdir -p /var/lib/tubesync/downloads
mkdir -p /var/lib/tubesync/data
chown -R tubesync:tubesync /var/lib/tubesync

# Create config directory
mkdir -p /etc/tubesync
chown tubesync:tubesync /etc/tubesync

# Create symlinks for XDG directories (so app finds config in expected location)
TUBESYNC_HOME="/var/lib/tubesync"
mkdir -p "$TUBESYNC_HOME/.config/tubesync"
mkdir -p "$TUBESYNC_HOME/.local/share/tubesync"
chown -R tubesync:tubesync "$TUBESYNC_HOME"

# Set HOME for the service
mkdir -p /etc/systemd/system/tubesync.service.d
cat > /etc/systemd/system/tubesync.service.d/home.conf << EOF
[Service]
Environment=HOME=/var/lib/tubesync
Environment=XDG_CONFIG_HOME=/var/lib/tubesync/.config
Environment=XDG_DATA_HOME=/var/lib/tubesync/.local/share
EOF

# Reload systemd
systemctl daemon-reload

# Enable and start service automatically
systemctl enable tubesync
systemctl start tubesync

# Update icon cache and desktop database
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

echo ""
echo "========================================"
echo " TubeSync installed and running!"
echo "========================================"
echo ""
echo "Open the web UI:"
echo "  http://localhost:9876"
echo ""
echo "First-time setup (all from web UI):"
echo "  1. Settings - configure SMB server"
echo "  2. Settings - upload Google API credentials"
echo "  3. Dashboard - click 'Authorize with Google'"
echo "  4. Done! Videos sync automatically every hour"
echo ""
POSTINST
chmod +x "$PACKAGE_DIR/DEBIAN/postinst"

# Create prerm script
cat > "$PACKAGE_DIR/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
set -e

# Stop service before removal
if systemctl is-active --quiet tubesync; then
    systemctl stop tubesync
fi

if systemctl is-enabled --quiet tubesync 2>/dev/null; then
    systemctl disable tubesync
fi
PRERM
chmod +x "$PACKAGE_DIR/DEBIAN/prerm"

# Create postrm script
cat > "$PACKAGE_DIR/DEBIAN/postrm" << 'POSTRM'
#!/bin/bash
set -e

case "$1" in
    remove)
        # Clean up systemd override
        rm -rf /etc/systemd/system/tubesync.service.d
        systemctl daemon-reload
        ;;
    purge)
        # Remove app directory
        rm -rf /opt/tubesync

        # Remove systemd override
        rm -rf /etc/systemd/system/tubesync.service.d
        systemctl daemon-reload

        # Remove user
        if id -u tubesync &>/dev/null; then
            userdel tubesync 2>/dev/null || true
        fi

        echo ""
        echo "Note: User data preserved in /var/lib/tubesync/"
        echo "Remove manually if no longer needed:"
        echo "  sudo rm -rf /var/lib/tubesync"
        echo ""
        ;;
esac
POSTRM
chmod +x "$PACKAGE_DIR/DEBIAN/postrm"

# Calculate installed size
INSTALLED_SIZE=$(du -sk "$PACKAGE_DIR" | cut -f1)
echo "Installed-Size: $INSTALLED_SIZE" >> "$PACKAGE_DIR/DEBIAN/control"

# Build the package
echo ""
echo "Building .deb package..."
dpkg-deb --build --root-owner-group "$PACKAGE_DIR"

# Move to dist folder
mkdir -p "$SCRIPT_DIR/dist"
mv "$BUILD_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb" "$SCRIPT_DIR/dist/"

# Cleanup
rm -rf "$BUILD_DIR"

echo ""
echo "==================================="
echo "Package built successfully!"
echo "==================================="
echo ""
echo "Output: $SCRIPT_DIR/dist/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo ""
echo "Install with:"
echo "  sudo dpkg -i dist/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo "  sudo apt-get install -f  # Install dependencies if needed"
echo ""
echo "Then start the service:"
echo "  sudo systemctl start tubesync"
echo "  sudo systemctl enable tubesync"
echo ""
echo "Access at: http://localhost:9876"
echo ""
