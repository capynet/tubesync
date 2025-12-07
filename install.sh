#!/bin/bash
# Tube Sync Installation Script
# For Debian/Ubuntu, Fedora, and Arch Linux

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==================================="
echo "Tube Sync Installation"
echo "==================================="

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Don't run as root. Run as regular user."
    exit 1
fi

# Detect OS
detect_os() {
    if [ -f /etc/debian_version ]; then
        echo "debian"
    elif [ -f /etc/fedora-release ]; then
        echo "fedora"
    elif [ -f /etc/arch-release ]; then
        echo "arch"
    else
        echo "unknown"
    fi
}

OS=$(detect_os)
echo "Detected OS: $OS"

# Install system dependencies
install_dependencies() {
    echo ""
    echo "Installing system dependencies..."

    case $OS in
        debian)
            PACKAGES="python3 python3-pip python3-venv python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg"
            MISSING=""

            for pkg in $PACKAGES; do
                if ! dpkg -s "$pkg" &> /dev/null; then
                    MISSING="$MISSING $pkg"
                fi
            done

            if [ -n "$MISSING" ]; then
                echo "Installing:$MISSING"
                sudo apt update -qq
                sudo apt install -y $MISSING
            else
                echo "[OK] All system dependencies already installed"
            fi
            ;;
        fedora)
            PACKAGES="python3 python3-pip ffmpeg gtk4 libadwaita python3-gobject"
            sudo dnf install -y $PACKAGES
            ;;
        arch)
            PACKAGES="python python-pip ffmpeg gtk4 libadwaita python-gobject"
            sudo pacman -S --needed --noconfirm $PACKAGES
            ;;
        *)
            echo "Unknown OS. Please install manually:"
            echo "  - Python 3.10+"
            echo "  - ffmpeg"
            echo "  - GTK4 + Libadwaita + PyGObject"
            read -p "Continue anyway? [y/N] " continue_install
            if [[ ! "$continue_install" =~ ^[Yy]$ ]]; then
                exit 1
            fi
            ;;
    esac
}

# Check Python version
check_python() {
    echo ""
    echo "Checking Python..."

    if ! command -v python3 &> /dev/null; then
        echo "Python 3 not found after installation. Please check your system."
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
        echo "Python 3.10+ required. Found: $PYTHON_VERSION"
        exit 1
    fi
    echo "[OK] Python $PYTHON_VERSION"
}

# Check ffmpeg
check_ffmpeg() {
    if ! command -v ffmpeg &> /dev/null; then
        echo "ffmpeg not found after installation. Please check your system."
        exit 1
    fi
    echo "[OK] ffmpeg found"
}

# Setup virtual environment
setup_venv() {
    echo ""
    echo "Setting up Python virtual environment..."

    if [ -d "$SCRIPT_DIR/venv" ]; then
        # Verify venv is valid
        if [ ! -f "$SCRIPT_DIR/venv/bin/activate" ]; then
            echo "Removing corrupted virtual environment..."
            rm -rf "$SCRIPT_DIR/venv"
        fi
    fi

    if [ ! -d "$SCRIPT_DIR/venv" ]; then
        python3 -m venv --system-site-packages "$SCRIPT_DIR/venv"
        echo "[OK] Virtual environment created"
    else
        echo "[OK] Virtual environment already exists"
    fi
}

# Install Python dependencies
install_python_deps() {
    echo ""
    echo "Installing Python dependencies (this may take a minute)..."
    source "$SCRIPT_DIR/venv/bin/activate"
    pip install --upgrade pip -q
    pip install -r "$SCRIPT_DIR/requirements.txt" -q
    echo "[OK] Dependencies installed"
}

# Create configuration
setup_config() {
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        echo ""
        echo "Creating .env from .env.example..."
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        echo "[!!] Edit .env with your configuration before starting"
    fi
}

# Create directories
create_directories() {
    echo ""
    echo "Creating directories..."
    mkdir -p "$SCRIPT_DIR/downloads"
    mkdir -p "$SCRIPT_DIR/data"
    echo "[OK] Directories created"
}

# Configure scripts
configure_scripts() {
    echo ""
    echo "Configuring scripts..."

    chmod +x "$SCRIPT_DIR/tubesync-gui"

    # Update shebang to use venv python
    sed -i "1s|.*|#!$SCRIPT_DIR/venv/bin/python3|" "$SCRIPT_DIR/tubesync-gui"
    echo "[OK] Scripts configured"
}

# Install commands globally
install_global_commands() {
    echo ""
    echo "Installing commands globally..."

    if [ -w /usr/local/bin ]; then
        ln -sf "$SCRIPT_DIR/tubesync-gui" /usr/local/bin/tubesync-gui
        ln -sf "$SCRIPT_DIR/tubesync-gui" /usr/local/bin/tubesync
        echo "[OK] Commands installed to /usr/local/bin/"
    else
        echo "Need sudo to install to /usr/local/bin..."
        sudo ln -sf "$SCRIPT_DIR/tubesync-gui" /usr/local/bin/tubesync-gui
        sudo ln -sf "$SCRIPT_DIR/tubesync-gui" /usr/local/bin/tubesync
        echo "[OK] Commands installed to /usr/local/bin/"
    fi
}

# Print completion message
print_completion() {
    echo ""
    echo "==================================="
    echo "Installation complete!"
    echo "==================================="
    echo ""
    echo "To start Tube Sync:"
    echo "  tubesync-gui"
    echo ""
    echo "Or find 'Tube Sync' in your applications menu."
    echo ""
    echo "Configuration is done through the GUI."
    echo "For YouTube API setup, see README.md."
    echo ""
}

# Main installation flow
main() {
    install_dependencies
    check_python
    check_ffmpeg
    setup_venv
    install_python_deps
    setup_config
    create_directories
    configure_scripts
    install_global_commands
    print_completion
}

main
