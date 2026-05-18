import os
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from .models import Base


def get_engine(database_url: str | None = None) -> Engine:
    """Create database engine. Supports SQLite, PostgreSQL, and MySQL."""
    if database_url is None:
        database_url = os.getenv("DATABASE_URL", "sqlite:///university.db")

    engine = create_engine(
        database_url,
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
    )
    return engine


def init_db(engine: Engine) -> None:
    """Create all tables."""
    Base.metadata.create_all(engine)


def get_session_factory(database_url: str | None = None) -> sessionmaker:
    """Get session factory for creating sessions."""
    engine = get_engine(database_url)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def get_session(database_url: str | None = None) -> Generator[Session, None, None]:
    """Get database session as context manager."""
    SessionLocal = get_session_factory(database_url)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
