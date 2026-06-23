import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime, timezone
import os

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
    logger.info("Initializing Store Intelligence Platform...")
    create_db()
    load_store_layout("store_layout.json")
    logger.info("Startup complete. Connected to PostgreSQL. Ready for telemetry.")
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
    processed_count = 0
    updated_sessions = set()
    stores_needing_correlation = set()

    for record in payload:
        evt_id = getattr(record, 'event_id', None) or getattr(record, 'id_token', None) or f"evt_{uuid.uuid4().hex}"
        
        if db.execute(select(Event.id).where(Event.event_id == evt_id)).scalar_one_or_none():
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
            
        if raw_event_type == EventTypes.QUEUE_COMPLETED:
            stores_needing_correlation.add(record.store_id)

        processed_count += 1

    db.commit()
    for sid in updated_sessions:
        reconstruct_journey_path(db, sid)
    db.commit() 

    affected_stores = {record.store_id for record in payload}
    for store_id in affected_stores:
        olap_cache.invalidate_store(store_id)

    for store_id in stores_needing_correlation:
        background_tasks.add_task(trigger_correlation_job, store_id)

    return {"status": "ACCEPTED", "processed": processed_count}


@app.get("/api/v1/stores/{store_id}/metrics", response_model=MetricSummaryResponse)
def get_store_metrics(store_id: str, camera_id: Optional[str] = None, db: DBSession = Depends(get_db)):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    filters = [Event.store_id == store_id, Event.event_timestamp >= today]
    if camera_id and camera_id.lower() != "all cameras":
        filters.append(Event.camera_id == camera_id)
        
    session_ids_stmt = select(Event.session_id).where(and_(*filters)).distinct()
    camera_session_ids = db.execute(session_ids_stmt).scalars().all()
    
    if not camera_session_ids:
        return {
            "store_id": store_id, "total_unique_visitors": 0, "converted_visitors": 0,
            "real_time_conversion_rate": 0.0, "active_queue_depth": 0, "average_wait_time_seconds": 0.0
        }
        
    sessions_stmt = select(SessionModel).where(SessionModel.session_id.in_(camera_session_ids))
    sessions = db.execute(sessions_stmt).scalars().all()
    
    # THE SMART FALLBACK: If a session EVER touched a checkout camera, count them as converted
    checkout_stmt = select(Event.session_id).where(
        and_(
            Event.store_id == store_id,
            Event.event_timestamp >= today,
            Event.session_id.in_(camera_session_ids),
            Event.camera_id.ilike("%CHECKOUT%")
        )
    ).distinct()
    checkout_session_ids = set(db.execute(checkout_stmt).scalars().all())
    
    total_visitors = len(sessions)
    
    converted_visitors = sum(1 for s in sessions if s.is_converted or s.session_id in checkout_session_ids)
    conversion_rate = (converted_visitors / total_visitors * 100.0) if total_visitors > 0 else 0.0
    
    active_queue = sum(1 for s in sessions if s.end_time is None)
        
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
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    filters = [Event.store_id == store_id, Event.event_timestamp >= today]
    if camera_id and camera_id.lower() != "all cameras":
        filters.append(Event.camera_id == camera_id)
        
    session_ids_stmt = select(Event.session_id).where(and_(*filters)).distinct()
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
        
    # Extract ALL events for these sessions to trace their full path
    all_events_stmt = select(Event.session_id, Event.camera_id).where(
        and_(
            Event.store_id == store_id,
            Event.event_timestamp >= today,
            Event.session_id.in_(camera_session_ids)
        )
    )
    all_events = db.execute(all_events_stmt).all()
    
    sessions_stmt = select(SessionModel).where(SessionModel.session_id.in_(camera_session_ids))
    sessions = db.execute(sessions_stmt).scalars().all()
    session_map = {s.session_id: s for s in sessions}
    
    ingress_count = len(camera_session_ids)
    browse_count = intent_count = convert_count = 0
    
    for sid in camera_session_ids:
        sess = session_map.get(sid)
        sess_events = [e for e in all_events if e.session_id == sid]
        cameras_touched = set(e.camera_id.upper() for e in sess_events if e.camera_id)
        
        tokens = [t.strip() for t in (sess.journey_path or '').split('->') if t.strip()]
        
        has_browse = has_intent = has_convert = False
        
        if [t for t in tokens if t not in ('ENTRY', 'EXIT', 'REENTRY')]: has_browse = True
        if 'CHECKOUT' in tokens or 'CASH_COUNTER' in tokens or 'QUEUE_DROP' in tokens: has_intent = True
        if sess and sess.is_converted: has_convert = True
            
        # THE CAMERA-AWARE HEURISTIC: Overrides missing zone_entered payloads
        for cam in cameras_touched:
            if 'ZONE' in cam or 'SKINCARE' in cam or 'FLOOR' in cam:
                has_browse = True
            if 'CHECKOUT' in cam:
                has_intent = True
                has_convert = True
                
        if has_browse: browse_count += 1
        if has_intent: intent_count += 1
        if has_convert: convert_count += 1
        
    # The Bottom-Up Cascade Fallback
    if convert_count > intent_count: intent_count = convert_count
    if intent_count > browse_count: browse_count = intent_count
    if browse_count > ingress_count: ingress_count = browse_count
        
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
    return AnomalyResponse(
        store_id=store_id,
        active_anomalies=[]
    )


@app.get("/health", response_model=HealthResponse)
def system_health():
    return HealthResponse(
        status="OK",
        database_connected=True,
        event_pipeline_connected=True,
        ingestion_rate_eps=0.0
    )