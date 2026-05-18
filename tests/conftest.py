import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.database.models import Base
from src.database.seed import seed_database


@pytest.fixture(scope="function")
def test_engine():
    """Create a test SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def test_session(test_engine):
    """Create a test database session."""
    SessionLocal = sessionmaker(bind=test_engine, class_=Session, expire_on_commit=False)
    session = SessionLocal()
    seed_database(session)
    yield session
    session.close()


@pytest.fixture
def seeded_engine(test_engine):
    """Engine with seed data."""
    SessionLocal = sessionmaker(bind=test_engine, class_=Session, expire_on_commit=False)
    session = SessionLocal()
    seed_database(session)
    session.close()
    return test_engine
