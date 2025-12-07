from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# SQLite connection args: enable WAL mode and set timeout for concurrent access
connect_args = {
    "timeout": 30,  # Wait up to 30 seconds for locked database
    "check_same_thread": False,
}

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        # Enable WAL mode for better concurrent read/write performance
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=30000"))  # 30 seconds
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
