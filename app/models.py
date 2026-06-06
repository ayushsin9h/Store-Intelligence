# VERSION 2
# Strictly aligned with the Purplle Tech Challenge Event Catalogue

from enum import Enum
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime, timezone
from typing import Optional, List, Literal

class EventType(str, Enum):
    # Enforcing strict uppercase string literals as per design specifications
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    QUEUE_COMPLETED = "QUEUE_COMPLETED"     # Maps to successful checkout
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventIngestionRecord(BaseModel):
    """
    Schema rigorously matched to the Purplle automated scoring harness.
    Fields are flattened to simplify analytics parsing.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Core Identifiers (Explicitly declared to prevent 'extra="ignore"' from dropping them)
    event_id: Optional[str] = None
    event_type: EventType
    store_id: str  # Enforced explicit naming to prevent ORM mapping issues
    camera_id: str
    
    # Tracking & Session IDs
    id_token: Optional[str] = None
    track_id: Optional[int] = None
    visitor_id: Optional[str] = None
    session_id: Optional[str] = None
    
    # ML Pipeline Confidence
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    
    # Timestamp handling
    event_timestamp: Optional[datetime] = Field(None, alias="event_time")
    
    # Demographics, Profiling, & Time State
    is_staff: Optional[bool] = False
    dwell_ms: Optional[int] = None  # Added as required by the updated schema
    gender_pred: Optional[str] = None
    age_pred: Optional[int] = None
    age_bucket: Optional[str] = None
    
    # Zone Specifics
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    zone_type: Optional[str] = None
    is_revenue_zone: Optional[str] = None
    zone_hotspot_x: Optional[float] = None
    zone_hotspot_y: Optional[float] = None
    
    # Queue Specifics
    queue_event_id: Optional[str] = None
    queue_join_ts: Optional[datetime] = None
    queue_served_ts: Optional[datetime] = None
    queue_exit_ts: Optional[datetime] = None
    wait_seconds: Optional[int] = None
    queue_position_at_join: Optional[int] = None
    abandoned: Optional[bool] = None

    @field_validator('event_timestamp', 'queue_join_ts', 'queue_served_ts', 'queue_exit_ts', mode='before')
    @classmethod
    def parse_and_normalize_datetime(cls, v):
        """Forgiving datetime parser that normalizes naive strings to UTC."""
        if not v:
            return None
        
        # Handle string parsing
        if isinstance(v, str):
            try:
                # Try parsing standard ISO format
                dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                return None 
        elif isinstance(v, datetime):
            dt = v
        else:
            return None

        # Normalize to UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

# --- Analytics Response Models ---

class FunnelStepResponse(BaseModel):
    stage_name: str
    visitor_count: int
    conversion_percentage: float

class StoreFunnelResponse(BaseModel):
    store_id: str
    window_start: datetime
    window_end: datetime
    funnel_stages: List[FunnelStepResponse]

class MetricSummaryResponse(BaseModel):
    store_id: str
    total_unique_visitors: int
    converted_visitors: int
    real_time_conversion_rate: float
    active_queue_depth: int
    average_wait_time_seconds: float

class HeatmapCoordinate(BaseModel):
    x: float
    y: float
    intensity: float

class HeatmapResponse(BaseModel):
    store_id: str
    zone_id: Optional[str] = None
    data_points: List[HeatmapCoordinate]

class AnomalyEvent(BaseModel):
    anomaly_id: str
    type: Literal["QUEUE_SPIKE", "CONVERSION_DROP", "DEAD_ZONE", "STALE_FEED"]
    severity: Literal["CRITICAL", "WARNING", "INFO"]
    description: str
    detected_at: datetime

class AnomalyResponse(BaseModel):
    store_id: str
    active_anomalies: List[AnomalyEvent]

class HealthResponse(BaseModel):
    status: Literal["OK", "DEGRADED", "OFFLINE"]
    database_connected: bool
    event_pipeline_connected: bool
    ingestion_rate_eps: float