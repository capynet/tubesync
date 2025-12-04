#!/usr/bin/env python3
"""
YT Sync GUI - Desktop application for monitoring and configuring YT Sync.
Built with Flet for native cross-platform support.
"""

import flet as ft
import httpx
import asyncio
from pathlib import Path

API_URL = "http://localhost:8000"
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def load_env() -> dict:
    """Load configuration from .env file."""
    config = {
        "NAS_ENABLED": "false",
        "NAS_HOST": "",
        "NAS_SHARE": "video",
        "NAS_USER": "",
        "NAS_PASSWORD": "",
        "NAS_PATH": "/youtube",
        "NAS_SHORTS_PATH": "/shorts",
        "NAS_DELETE_AFTER_UPLOAD": "false",
        "SHORTS_MAX_DURATION": "60",
    }

    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()

    return config


def save_env(config: dict):
    """Save configuration to .env file."""
    lines = []
    config_copy = config.copy()

    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped or "=" not in stripped:
                    lines.append(line.rstrip())
                else:
                    key = stripped.split("=", 1)[0].strip()
                    if key in config_copy:
                        lines.append(f"{key}={config_copy[key]}")
                        del config_copy[key]
                    else:
                        lines.append(line.rstrip())

    for key, value in config_copy.items():
        lines.append(f"{key}={value}")

    with open(ENV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


def format_speed(bytes_per_sec: int) -> str:
    """Format speed to human readable."""
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / 1024 / 1024:.1f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    return f"{bytes_per_sec:.0f} B/s"


async def fetch_api_data() -> dict:
    """Fetch all data from API."""
    data = {
        "stats": {},
        "auto_status": {},
        "upload_progress": {},
        "download_progress": {},
        "connected": False,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{API_URL}/api/stats")
                data["stats"] = resp.json() if resp.status_code == 200 else {}
            except:
                pass

            try:
                resp = await client.get(f"{API_URL}/api/auto-download/status")
                data["auto_status"] = resp.json() if resp.status_code == 200 else {}
            except:
                pass

            try:
                resp = await client.get(f"{API_URL}/api/uploads/progress")
                data["upload_progress"] = resp.json() if resp.status_code == 200 else {}
            except:
                pass

            try:
                resp = await client.get(f"{API_URL}/api/downloads/progress")
                data["download_progress"] = resp.json() if resp.status_code == 200 else {}
            except:
                pass

            data["connected"] = bool(data["stats"])
    except:
        pass

    return data


async def main(page: ft.Page):
    """Main Flet application."""
    page.title = "YT Sync"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.window.width = 900
    page.window.height = 700
    page.padding = 0

    running = True
    current_view = "dashboard"

    # ==================== Stats Controls ====================
    downloads_completed = ft.Text("0", size=32, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN)
    downloads_pending = ft.Text("0", size=16)
    downloads_errors = ft.Text("0", size=16, color=ft.Colors.RED)
    downloads_today = ft.Text("0", size=16)
    total_size = ft.Text("0 MB", size=14)

    uploads_completed = ft.Text("0", size=32, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE)
    uploads_pending = ft.Text("0", size=16)
    uploads_errors = ft.Text("0", size=16, color=ft.Colors.RED)
    uploads_today = ft.Text("0", size=16)

    api_status = ft.Text("Checking...", size=14)
    subscriptions_count = ft.Text("0", size=32, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE)
    last_run = ft.Text("Never", size=14)
    last_queued = ft.Text("0", size=14)

    connection_status = ft.Text("Connecting...", color=ft.Colors.ORANGE)
    connection_icon = ft.Icon(ft.Icons.CIRCLE, size=12, color=ft.Colors.ORANGE)

    download_progress_column = ft.Column([], spacing=5)
    upload_progress_column = ft.Column([], spacing=5)

    def create_stat_card(title: str, main_value: ft.Control, details: list) -> ft.Card:
        return ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_500),
                    main_value,
                    ft.Divider(height=1),
                    *[ft.Row([
                        ft.Text(label, size=12, color=ft.Colors.GREY_600),
                        value
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN) for label, value in details]
                ], spacing=8),
                padding=15,
            ),
            expand=True,
        )

    def create_progress_item(title: str, percent: float, speed: int, is_upload: bool = False) -> ft.Container:
        icon = ft.Icons.CLOUD_UPLOAD if is_upload else ft.Icons.CLOUD_DOWNLOAD
        color = ft.Colors.ORANGE if is_upload else ft.Colors.BLUE

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(icon, size=16, color=color),
                    ft.Text(title[:50], size=12, expand=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{percent:.1f}%", size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(format_speed(speed) if speed > 0 else "", size=11, color=ft.Colors.GREY_500),
                ], spacing=8),
                ft.ProgressBar(value=percent/100, color=color, bgcolor=ft.Colors.GREY_300),
            ], spacing=4),
            padding=ft.padding.only(bottom=8),
        )

    async def update_dashboard():
        data = await fetch_api_data()

        if not data["connected"]:
            connection_status.value = "Disconnected"
            connection_status.color = ft.Colors.RED
            connection_icon.color = ft.Colors.RED
        else:
            connection_status.value = "Connected"
            connection_status.color = ft.Colors.GREEN
            connection_icon.color = ft.Colors.GREEN

        dl = data["stats"].get("downloads", {})
        downloads_completed.value = str(dl.get("completed", 0))
        downloads_pending.value = str(dl.get("pending", 0))
        downloads_errors.value = str(dl.get("errors", 0))
        downloads_today.value = str(dl.get("today", 0))
        total_size.value = f"{data['stats'].get('total_size_mb', 0):.0f} MB"

        up = data["stats"].get("uploads", {})
        uploads_completed.value = str(up.get("uploaded", 0))
        uploads_pending.value = str(up.get("pending", 0))
        uploads_errors.value = str(up.get("errors", 0))
        uploads_today.value = str(up.get("today", 0))

        auto = data["stats"].get("auto_download", {})
        subscriptions_count.value = str(data["auto_status"].get("subscription_count", 0))

        api_configured = data["auto_status"].get("api_configured", False)
        quota_exceeded = data["auto_status"].get("quota_exceeded", False)

        if quota_exceeded:
            api_status.value = "QUOTA EXCEEDED"
            api_status.color = ft.Colors.RED
        elif api_configured:
            api_status.value = "OK"
            api_status.color = ft.Colors.GREEN
        else:
            api_status.value = "NOT CONFIGURED"
            api_status.color = ft.Colors.ORANGE

        lr = auto.get("last_run", "Never")
        if lr and lr != "Never" and "T" in str(lr):
            lr = str(lr).split("T")[1][:8]
        last_run.value = str(lr) if lr else "Never"
        last_queued.value = str(auto.get("last_run_queued", 0))

        download_progress_column.controls.clear()
        active_downloads = data["download_progress"].get("downloads", [])
        if active_downloads:
            for dl_item in active_downloads:
                download_progress_column.controls.append(
                    create_progress_item(
                        dl_item.get("title", "Unknown"),
                        dl_item.get("percent", 0),
                        dl_item.get("speed", 0),
                        is_upload=False
                    )
                )
        else:
            pending = data["stats"].get("downloads", {}).get("pending", 0)
            msg = f"{pending} videos in queue..." if pending > 0 else "No active downloads"
            download_progress_column.controls.append(
                ft.Text(msg, color=ft.Colors.GREY_500, size=12)
            )

        upload_progress_column.controls.clear()
        active_uploads = data["upload_progress"].get("uploads", [])
        if active_uploads:
            for up_item in active_uploads:
                upload_progress_column.controls.append(
                    create_progress_item(
                        up_item.get("title", "Unknown"),
                        up_item.get("percent", 0),
                        up_item.get("speed", 0),
                        is_upload=True
                    )
                )
        else:
            pending = data["stats"].get("uploads", {}).get("pending", 0)
            msg = f"{pending} videos waiting..." if pending > 0 else "No pending uploads"
            upload_progress_column.controls.append(
                ft.Text(msg, color=ft.Colors.GREY_500, size=12)
            )

        page.update()

    async def refresh_loop():
        while running:
            try:
                if current_view == "dashboard":
                    await update_dashboard()
            except Exception as e:
                print(f"Update error: {e}")
            await asyncio.sleep(2)

    # ==================== Dashboard View ====================
    downloads_card = create_stat_card("Downloads", downloads_completed, [
        ("Pending", downloads_pending),
        ("Errors", downloads_errors),
        ("Today", downloads_today),
        ("Total Size", total_size),
    ])

    uploads_card = create_stat_card("NAS Uploads", uploads_completed, [
        ("Pending", uploads_pending),
        ("Errors", uploads_errors),
        ("Today", uploads_today),
    ])

    auto_card = create_stat_card("Auto-Download", subscriptions_count, [
        ("YouTube API", api_status),
        ("Last Run", last_run),
        ("Last Queued", last_queued),
    ])

    dashboard_content = ft.Container(
        content=ft.Column([
            ft.Row([connection_icon, connection_status], spacing=5),
            ft.Divider(height=20),
            ft.ResponsiveRow([
                ft.Container(downloads_card, col={"sm": 12, "md": 4}),
                ft.Container(uploads_card, col={"sm": 12, "md": 4}),
                ft.Container(auto_card, col={"sm": 12, "md": 4}),
            ]),
            ft.Divider(height=20),
            ft.ResponsiveRow([
                ft.Container(
                    content=ft.Column([
                        ft.Text("Active Downloads", weight=ft.FontWeight.BOLD, size=14),
                        download_progress_column,
                    ]),
                    col={"sm": 12, "md": 6},
                    padding=10,
                    border=ft.border.all(1, ft.Colors.GREY_300),
                    border_radius=8,
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("NAS Uploads", weight=ft.FontWeight.BOLD, size=14),
                        upload_progress_column,
                    ]),
                    col={"sm": 12, "md": 6},
                    padding=10,
                    border=ft.border.all(1, ft.Colors.GREY_300),
                    border_radius=8,
                ),
            ]),
        ], scroll=ft.ScrollMode.AUTO),
        padding=20,
        expand=True,
    )

    # ==================== Settings View ====================
    config = load_env()

    nas_enabled = ft.Switch(value=config.get("NAS_ENABLED", "false").lower() == "true")
    nas_host = ft.TextField(label="NAS Host", value=config.get("NAS_HOST", ""), hint_text="192.168.1.100", expand=True)
    nas_share = ft.TextField(label="Share Name", value=config.get("NAS_SHARE", "video"), expand=True)
    nas_user = ft.TextField(label="Username", value=config.get("NAS_USER", ""), expand=True)
    nas_password = ft.TextField(label="Password", value=config.get("NAS_PASSWORD", ""), password=True, can_reveal_password=True, expand=True)
    nas_path = ft.TextField(label="Videos Path", value=config.get("NAS_PATH", "/youtube"), expand=True)
    nas_shorts_path = ft.TextField(label="Shorts Path", value=config.get("NAS_SHORTS_PATH", "/shorts"), expand=True)
    nas_delete_after = ft.Switch(value=config.get("NAS_DELETE_AFTER_UPLOAD", "false").lower() == "true")
    shorts_duration = ft.TextField(label="Max Shorts Duration (seconds)", value=config.get("SHORTS_MAX_DURATION", "60"), keyboard_type=ft.KeyboardType.NUMBER, width=200)

    save_status = ft.Text("", size=12)

    def save_settings(e):
        new_config = {
            "NAS_ENABLED": "true" if nas_enabled.value else "false",
            "NAS_HOST": nas_host.value,
            "NAS_SHARE": nas_share.value,
            "NAS_USER": nas_user.value,
            "NAS_PASSWORD": nas_password.value,
            "NAS_PATH": nas_path.value,
            "NAS_SHORTS_PATH": nas_shorts_path.value,
            "NAS_DELETE_AFTER_UPLOAD": "true" if nas_delete_after.value else "false",
            "SHORTS_MAX_DURATION": shorts_duration.value,
        }

        try:
            save_env(new_config)
            save_status.value = "Saved! Restart service to apply."
            save_status.color = ft.Colors.GREEN
        except Exception as ex:
            save_status.value = f"Error: {ex}"
            save_status.color = ft.Colors.RED

        page.update()

    settings_content = ft.Container(
        content=ft.Column([
            ft.Text("NAS Configuration", size=20, weight=ft.FontWeight.BOLD),
            ft.Divider(height=20),
            ft.Row([ft.Text("Enable NAS Upload", size=14, expand=True), nas_enabled]),
            ft.Divider(height=10),
            ft.Row([nas_host, nas_share], spacing=15),
            ft.Row([nas_user, nas_password], spacing=15),
            ft.Row([nas_path, nas_shorts_path], spacing=15),
            ft.Divider(height=20),
            ft.Row([ft.Text("Delete local after upload", size=14, expand=True), nas_delete_after]),
            ft.Row([shorts_duration]),
            ft.Divider(height=20),
            ft.Row([
                ft.ElevatedButton("Save Settings", icon=ft.Icons.SAVE, on_click=save_settings),
                save_status,
            ], spacing=15),
            ft.Text("Restart yt-sync-service for changes to take effect.", size=12, color=ft.Colors.GREY_500, italic=True),
        ], spacing=15, scroll=ft.ScrollMode.AUTO),
        padding=20,
        expand=True,
    )

    # ==================== Navigation ====================
    content_area = ft.Container(content=dashboard_content, expand=True)

    def switch_view(e):
        nonlocal current_view
        idx = e.control.selected_index
        current_view = "dashboard" if idx == 0 else "settings"
        content_area.content = dashboard_content if idx == 0 else settings_content
        page.update()

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=80,
        min_extended_width=150,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD, label="Dashboard"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS, label="Settings"),
        ],
        on_change=switch_view,
    )

    page.add(
        ft.Row([
            rail,
            ft.VerticalDivider(width=1),
            content_area,
        ], expand=True)
    )

    # Start refresh loop
    page.run_task(refresh_loop)


if __name__ == "__main__":
    ft.app(target=main)
