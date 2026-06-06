# app/engines/sessions.py

import uuid
import logging
from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select, and_, asc

# CRITICAL FIX 1: Aliasing Session to SessionModel to prevent ORM shadowing
from app.storage.database import Event, Session as SessionModel

logger = logging.getLogger(__name__)

class EventTypes:
    """Strict alignment with models.py and zones.py to prevent silent event drops."""
    ENTRY = "entry"
    EXIT = "exit"
    ZONE_ENTERED = "zone_entered"
    ZONE_EXITED = "zone_exited"
    QUEUE_COMPLETED = "queue_completed"
    QUEUE_ABANDONED = "queue_abandoned"
    REENTRY = "reentry"

# CRITICAL FIX 3: 5 minutes is a realistic "stepped out for a call" threshold
SESSION_TIMEOUT_SECONDS = 5 * 60  

def get_or_create_session(
    db: DBSession, store_id: str, visitor_id: Optional[str], event_time: datetime
) -> Tuple[str, bool]:
    """
    State manager for identities.
    Returns: (session_id: str, is_reentry: bool)
    The is_reentry flag tells the upstream router to explicitly emit a REENTRY event.
    """
    # CRITICAL FIX 2: Dynamic anonymous provisioning prevents ghost-merging
    if not visitor_id:
        visitor_id = f"anon_{uuid.uuid4().hex[:8]}"
        logger.warning(f"Null visitor_id for store {store_id}. Provisioned isolated track {visitor_id}.")

    # O(1) lookup via limit
    stmt = (
        select(SessionModel)
        .where(
            and_(
                SessionModel.store_id == store_id,
                SessionModel.visitor_id == visitor_id
            )
        )
        .order_by(SessionModel.start_time.desc())
        .limit(1)
    )
    
    latest_session = db.execute(stmt).scalar_one_or_none()

    if latest_session:
        # If the session hasn't explicitly ended, keep using it
        if latest_session.end_time is None:
            return latest_session.session_id, False
            
        # SECOND TIMEZONE FIX: Stripping tzinfo for safe re-entry subtraction
        time_since_exit = (event_time.replace(tzinfo=None) - latest_session.end_time.replace(tzinfo=None)).total_seconds()
        
        # CRITICAL FIX 4: Catch the re-entry and return the flag
        if 0 <= time_since_exit < SESSION_TIMEOUT_SECONDS:
            latest_session.end_time = None
            db.commit()
            return latest_session.session_id, True  # REENTRY triggered

    # Provision a brand new session ledger
    new_session_id = f"sess_{store_id}_{visitor_id}_{event_time.strftime('%Y%m%d%H%M%S')}"
    
    new_session = SessionModel(
        session_id=new_session_id,
        store_id=store_id,
        visitor_id=visitor_id,
        start_time=event_time,
        is_converted=False,
        total_dwell_seconds=0
    )
    
    db.add(new_session)
    db.commit()
    
    return new_session_id, False


def close_session(db: DBSession, session_id: str, exit_time: datetime) -> None:
    """Explicitly caps a session when an 'exit' event triggers."""
    session = db.execute(select(SessionModel).where(SessionModel.session_id == session_id)).scalar_one_or_none()
    
    if session and (session.end_time is None or exit_time.replace(tzinfo=None) > session.end_time.replace(tzinfo=None)):
        session.end_time = exit_time.replace(tzinfo=None)
        
        # FIRST TIMEZONE FIX (You successfully added this!)
        duration = (exit_time.replace(tzinfo=None) - session.start_time.replace(tzinfo=None)).total_seconds()
        if duration > 0:
            session.total_dwell_seconds = int(duration)
            
        db.commit()


def reconstruct_journey_path(db: DBSession, session_id: str) -> Optional[str]:
    """
    Powers: GET /funnel
    Scans the event ledger to build a chronological journey sequence.
    """
    stmt = (
        select(Event)
        .where(Event.session_id == session_id)
        .order_by(Event.event_timestamp.asc())
    )
    
    events = db.execute(stmt).scalars().all()
    if not events:
        return None
        
    path_sequence: List[str] = []
    
    for event in events:
        if event.event_type == EventTypes.ENTRY:
            if not path_sequence or path_sequence[-1] != "ENTRY":
                path_sequence.append("ENTRY")
                
        elif event.event_type == EventTypes.REENTRY:
            if not path_sequence or path_sequence[-1] != "REENTRY":
                path_sequence.append("REENTRY")
                
        elif event.event_type == EventTypes.ZONE_ENTERED:
            zone_name = event.event_data.get("zone_name", "UNKNOWN_ZONE")
            if not path_sequence or path_sequence[-1] != zone_name:
                path_sequence.append(zone_name)
                
        elif event.event_type == EventTypes.QUEUE_COMPLETED:
            if not path_sequence or path_sequence[-1] != "CHECKOUT":
                path_sequence.append("CHECKOUT")
                
        elif event.event_type == EventTypes.QUEUE_ABANDONED:
            if not path_sequence or path_sequence[-1] != "QUEUE_DROP":
                path_sequence.append("QUEUE_DROP")
                
        elif event.event_type == EventTypes.EXIT:
            if not path_sequence or path_sequence[-1] != "EXIT":
                path_sequence.append("EXIT")

    journey_str = " -> ".join(path_sequence)
    
    # Materialize the journey string back to the database for fast polling
    session = db.execute(select(SessionModel).where(SessionModel.session_id == session_id)).scalar_one_or_none()
    if session:
        session.journey_path = journey_str
        db.commit()
        
    return journey_str


def mark_session_converted(db: DBSession, session_id: str) -> None:
    """Flags the session as financially converted."""
    session = db.execute(select(SessionModel).where(SessionModel.session_id == session_id)).scalar_one_or_none()
    if session and not session.is_converted:
        session.is_converted = True
        db.commit()