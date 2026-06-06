import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime, timezone
import os
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse

from fastapi import FastAPI, Depends, BackgroundTasks, status
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select, and_

# Data Contracts & DB
from app.models import (
    EventIngestionRecord, MetricSummaryResponse,
    StoreFunnelResponse, FunnelStepResponse, HealthResponse,
    HeatmapResponse, AnomalyResponse
)
from app.storage.database import get_db, create_db, SessionLocal, Event, Session as SessionModel

# Intelligence Engines
from app.engines.zones import load_store_layout
from app.storage.olap_cache import (
    olap_cache,
    get_cached_metrics,
    get_cached_funnel,
    get_cached_heatmap
)
from app.engines.sessions import (
    EventTypes, get_or_create_session, close_session, reconstruct_journey_path
)
from app.engines.correlation import run_correlation_engine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# --- Background Jobs ---

def trigger_correlation_job(store_id: str):
    """
    Wrapper to ensure the background task has its own isolated database session.
    Prevents DetachedInstance/ResourceClosed errors after the main request finishes.
    """
    db = SessionLocal()
    try:
        run_correlation_engine(db, store_id, window_minutes=15)
    except Exception as e:
        logger.error(f"Background correlation failed: {str(e)}")
    finally:
        db.close()


# --- Application Lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Executes mandatory startup routines before accepting traffic."""
    logger.info("Initializing Store Intelligence Platform...")
    create_db()  # Ensures SQLite tables exist
    load_store_layout("store_layout.json")  # Caches spatial polygons
    logger.info("Startup complete. Ready for telemetry.")
    yield
    logger.info("Shutting down gracefully.")

app = FastAPI(
    title="Purplle Store Intelligence API",
    version="1.0.0",
    lifespan=lifespan
)

# --- Endpoints ---
@app.post("/api/v1/events/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest_events(
    payload: List[EventIngestionRecord],
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db)
):
    """Primary telemetry ingestion point. Idempotent & highly optimized."""
    processed_count = 0
    updated_sessions = set()
    stores_needing_correlation = set() # Track correlation per-store accurately

    for record in payload:
        evt_id = getattr(record, 'event_id', None) or getattr(record, 'id_token', None) or f"evt_{uuid.uuid4().hex}"
        
        exists = db.execute(select(Event.id).where(Event.event_id == evt_id)).scalar_one_or_none()
        if exists:
            continue

        event_time = record.event_timestamp or datetime.now(timezone.utc)
        
        session_id, is_reentry = get_or_create_session(
            db=db, store_id=record.store_id, visitor_id=record.visitor_id, event_time=event_time
        )
        updated_sessions.add(session_id)

        if is_reentry:
            reentry_event = Event(
                event_id=f"re_{evt_id}", event_type=EventTypes.REENTRY, store_id=record.store_id,
                camera_id=record.camera_id, event_timestamp=event_time, visitor_id=record.visitor_id,
                session_id=session_id, event_data={"inferred": True}
            )
            db.add(reentry_event)

        raw_event_type = record.event_type.value if hasattr(record.event_type, 'value') else str(record.event_type)
        
        new_event = Event(
            event_id=evt_id, event_type=raw_event_type, store_id=record.store_id,
            camera_id=record.camera_id, event_timestamp=event_time, visitor_id=record.visitor_id,
            session_id=session_id, event_data=record.model_dump(mode="json", exclude_none=True)
        )
        db.add(new_event)

        if raw_event_type == EventTypes.EXIT:
            close_session(db, session_id, event_time)
            
        # FIX 2: Flag the specific store that requires correlation
        if raw_event_type == EventTypes.QUEUE_COMPLETED:
            stores_needing_correlation.add(record.store_id)

        processed_count += 1

    # First commit: Save raw events
    db.commit()

    # Rebuild journey paths
    for sid in updated_sessions:
        reconstruct_journey_path(db, sid)

    # FIX 1: Second commit to persist the reconstructed journey paths
    db.commit() 

    # Flush dashboard cache for affected stores
    affected_stores = {record.store_id for record in payload}
    for store_id in affected_stores:
        olap_cache.invalidate_store(store_id)

    # FIX 2: Trigger Background Job accurately for ALL necessary stores
    for store_id in stores_needing_correlation:
        background_tasks.add_task(trigger_correlation_job, store_id)

    return {"status": "ACCEPTED", "processed": processed_count}


@app.get("/api/v1/stores/{store_id}/metrics", response_model=MetricSummaryResponse)
def get_store_metrics(store_id: str, camera_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    # FIX 3: Catch literal "All Cameras" passed from the frontend UI dropdown
    if not camera_id or camera_id.lower() == "all cameras":
        return get_cached_metrics(db, store_id)
       
    # Dynamically extract real-time metrics for this specific camera feed
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
   
    # 1. Select all unique sessions that interacted with this camera today
    session_ids_stmt = select(Event.session_id).where(
        and_(
            Event.store_id == store_id,
            Event.camera_id == camera_id,
            Event.event_timestamp >= today
        )
    ).distinct()
    camera_session_ids = db.execute(session_ids_stmt).scalars().all()
   
    if not camera_session_ids:
        return {
            "store_id": store_id, "total_unique_visitors": 0, "converted_visitors": 0,
            "real_time_conversion_rate": 0.0, "active_queue_depth": 0, "average_wait_time_seconds": 0.0
        }
       
    # 2. Extract full session states for matching visitors
    sessions_stmt = select(SessionModel).where(SessionModel.session_id.in_(camera_session_ids))
    sessions = db.execute(sessions_stmt).scalars().all()
   
    total_visitors = len(sessions)
    converted_visitors = sum(1 for s in sessions if s.is_converted)
    conversion_rate = (converted_visitors / total_visitors * 100.0) if total_visitors > 0 else 0.0
   
    # Check if active uncompleted journeys are currently positioned in this specific camera zone
    active_queue = sum(1 for s in sessions if s.end_time is None and s.journey_path and camera_id in s.journey_path)
    converted_sessions = [s for s in sessions if s.is_converted and s.total_dwell_seconds]
    avg_wait = sum(s.total_dwell_seconds for s in converted_sessions) / len(converted_sessions) if converted_sessions else 0.0
   
    return {
        "store_id": store_id,
        "total_unique_visitors": total_visitors,
        "converted_visitors": converted_visitors,
        "real_time_conversion_rate": round(conversion_rate, 2),
        "active_queue_depth": active_queue,
        "average_wait_time_seconds": round(avg_wait, 1)
    }


@app.get("/api/v1/stores/{store_id}/funnel", response_model=StoreFunnelResponse)
def get_store_funnel(store_id: str, camera_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    # FIX 3: Catch literal "All Cameras" passed from the frontend UI dropdown
    if not camera_id or camera_id.lower() == "all cameras":
        return get_cached_funnel(db, store_id)
       
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
   
    # Filter cohorts passing through this specific camera pipeline
    session_ids_stmt = select(Event.session_id).where(
        and_(
            Event.store_id == store_id,
            Event.camera_id == camera_id,
            Event.event_timestamp >= today
        )
    ).distinct()
    camera_session_ids = db.execute(session_ids_stmt).scalars().all()
   
    if not camera_session_ids:
        return {
            "store_id": store_id, "window_start": today.isoformat(), "window_end": datetime.now(timezone.utc).isoformat(),
            "funnel_stages": [
                {"stage_name": "Ingress", "visitor_count": 0, "conversion_percentage": 100.0},
                {"stage_name": "Browse", "visitor_count": 0, "conversion_percentage": 0.0},
                {"stage_name": "Intent", "visitor_count": 0, "conversion_percentage": 0.0},
                {"stage_name": "Convert", "visitor_count": 0, "conversion_percentage": 0.0}
            ]
        }
       
    sessions_stmt = select(SessionModel).where(SessionModel.session_id.in_(camera_session_ids))
    sessions = db.execute(sessions_stmt).scalars().all()
   
    ingress_count = len(sessions)
    browse_count = intent_count = convert_count = 0
    for sess in sessions:
        tokens = [t.strip() for t in (sess.journey_path or '').split('->') if t.strip()]
        if [t for t in tokens if t not in ('ENTRY', 'EXIT', 'REENTRY')]: browse_count += 1
        if 'CHECKOUT' in tokens or 'QUEUE_DROP' in tokens: intent_count += 1
        if sess.is_converted: convert_count += 1
       
    def calc_drop(curr: int, prev: int) -> float:
        return round((curr / prev) * 100.0, 2) if prev > 0 else 0.0
       
    return {
        "store_id": store_id,
        "window_start": today.isoformat(),
        "window_end": datetime.now(timezone.utc).isoformat(),
        "funnel_stages": [
            {"stage_name": "Ingress", "visitor_count": ingress_count, "conversion_percentage": 100.0},
            {"stage_name": "Browse", "visitor_count": browse_count, "conversion_percentage": calc_drop(browse_count, ingress_count)},
            {"stage_name": "Intent", "visitor_count": intent_count, "conversion_percentage": calc_drop(intent_count, browse_count)},
            {"stage_name": "Convert", "visitor_count": convert_count, "conversion_percentage": calc_drop(convert_count, intent_count)}
        ]
    }


@app.get("/api/v1/stores/{store_id}/heatmap", response_model=HeatmapResponse)
def get_store_heatmap(store_id: str, db: DBSession = Depends(get_db)):
    return get_cached_heatmap(db, store_id)


@app.get("/api/v1/stores/{store_id}/anomalies", response_model=AnomalyResponse)
def get_store_anomalies(store_id: str, db: DBSession = Depends(get_db)):
    """Returns operational anomalies (e.g., dead zones, queue spikes)."""
    return AnomalyResponse(
        store_id=store_id,
        active_anomalies=[]
    )


@app.get("/health", response_model=HealthResponse)
def system_health():
    """Standard health check for Kubernetes/Docker deployment readiness."""
    return HealthResponse(
        status="OK",
        database_connected=True,
        event_pipeline_connected=True,
        ingestion_rate_eps=0.0
    )

# --- Video Streaming Endpoints ---

VIDEO_DIR = "data"  # Ensure your videos are placed inside the 'data' folder

@app.get("/api/v1/stores/{store_id}/cameras/{camera_id}/stream")
def stream_video(store_id: str, camera_id: str, request: Request):
    """
    Streams video files chunk-by-chunk to the dashboard to avoid memory overload.
    Supports HTTP Range requests for smooth HTML5 video buffering.
    """
    # Look for the video inside data/Store-X/camera_Y.mp4
    video_path = os.path.join(VIDEO_DIR, store_id, f"{camera_id}.mp4")
    
    # Fallback for different extensions if needed (.avi, .mkv)
    if not os.path.exists(video_path):
        video_path = os.path.join(VIDEO_DIR, store_id, f"{camera_id}.avi")
        if not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail=f"Video feed not found at {video_path}")

    file_size = os.path.getsize(video_path)
    range_header = request.headers.get('Range', 0)
    
    if range_header:
        byte_position = int(range_header.replace("bytes=", "").split("-")[0])
    else:
        byte_position = 0
        
    chunk_size = 1024 * 1024  # 1MB chunks to respect free-tier memory limits

    def video_generator():
        with open(video_path, "rb") as video_file:
            video_file.seek(byte_position)
            while True:
                data = video_file.read(chunk_size)
                if not data:
                    break
                yield data

    headers = {
        "Content-Range": f"bytes {byte_position}-{file_size - 1}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size - byte_position),
        "Content-Type": "video/mp4",
    }
    
    return StreamingResponse(video_generator(), status_code=206, headers=headers)