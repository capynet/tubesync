from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Channel(Base):
    """Track subscribed channels and their sync state."""
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    channel_name: Mapped[str] = mapped_column(String(200))
    thumbnail: Mapped[str] = mapped_column(String(500), default="")
    last_checked: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_video_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_video_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppState(Base):
    """Key-value store for app state that needs to persist."""
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    channel: Mapped[str] = mapped_column(String(200))
    duration: Mapped[int] = mapped_column(Integer, default=0)  # seconds
    thumbnail: Mapped[str] = mapped_column(String(500), default="")
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, downloading, completed, error
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    download_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # SMB Upload tracking (nas_path kept for DB backwards compatibility)
    upload_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, uploading, uploaded, error
    upload_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    nas_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # SMB path (legacy column name)
    upload_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # FTP Upload tracking
    ftp_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, uploading, uploaded, error
    ftp_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    ftp_uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ftp_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Path on FTP
    ftp_attempts: Mapped[int] = mapped_column(Integer, default=0)
