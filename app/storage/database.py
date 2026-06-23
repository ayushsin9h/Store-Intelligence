# app/storage/database.py
import os
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import create_engine, String, Float, DateTime, JSON, Boolean, Integer, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:yourpassword@localhost:5432/store_intelligence"
)

# PostgreSQL natively handles multi-threading and connection pooling.
# We remove the SQLite "check_same_thread" hack.
engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

# 2. Schema Definitions

class Event(Base):
    """Immutable ledger of all CV detections and zone transitions."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, unique=True, index=True) # Critical for idempotency
    event_type: Mapped[str] = mapped_column(String, index=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    camera_id: Mapped[str] = mapped_column(String)
    
    # Aligned with models.py
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    
    # Core Identifiers
    visitor_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    
    # Flexible JSON payload for varying metadata
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Session(Base):
    """The reconstructed journey of a customer from entry to exit."""
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    visitor_id: Mapped[str] = mapped_column(String, index=True)
    
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    
    # Explicitly nullable to prevent SQLite inference issues
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Stores sequence like "ENTRY→MINIMALIST→LOREAL→QUEUE" for funnel analytics
    journey_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    is_converted: Mapped[bool] = mapped_column(Boolean, default=False)
    total_dwell_seconds: Mapped[int] = mapped_column(Integer, default=0)


class Transaction(Base):
    """Parsed entries from POS - sample transactionsb1e826f.csv"""
    __tablename__ = "transactions"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    
    brand_name: Mapped[str] = mapped_column(String, index=True)
    total_amount: Mapped[float] = mapped_column(Float)
    
    session_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)

    # Composite index to optimize fast lookups by the POS Correlation Engine
    __table_args__ = (
        Index('idx_transaction_store_time', 'store_id', 'timestamp'),
    )


class Anomaly(Base):
    """System health and store operational alerts."""
    __tablename__ = "anomalies"

    anomaly_id: Mapped[str] = mapped_column(String, primary_key=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    anomaly_type: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    detected_at: Mapped[datetime] = mapped_column(DateTime, index=True)


# 3. Database Initialization & Dependency Injection
def create_db():
    """Initializes the SQLite database tables. Required on app startup."""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Yields an isolated database session for a single FastAPI request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()