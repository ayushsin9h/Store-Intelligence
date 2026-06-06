# app/engines/correlation.py

import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select, and_, desc

from app.storage.database import Session as SessionModel, Transaction, Event
from app.engines.sessions import mark_session_converted

logger = logging.getLogger(__name__)

# --- Tuning Parameters (Ensemble Weights) ---
TIME_VARIANCE_SECONDS = 45.0  
WEIGHT_TEMPORAL = 0.75
WEIGHT_AFFINITY = 0.25
MATCH_CONFIDENCE_THRESHOLD = 0.60  


def normalize_string_for_match(text: Optional[str]) -> str:
    """Strips all special characters and spaces for robust brand matching (e.g. L'Oreal -> loreal)."""
    if not text:
        return ""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def calculate_brand_affinity(brand_name: str, session_journey: Optional[str]) -> float:
    """
    Checks if a session's journey path includes zones related to the purchased brand.
    Returns 1.0 for a match, 0.0 for no match.
    Tokenized to prevent substring false positives (e.g., 'mac' in 'smacker_zone').
    """
    if not session_journey:
        return 0.0
        
    normalized_brand = normalize_string_for_match(brand_name)
    
    # Tokenize journey path safely
    journey_tokens = {
        normalize_string_for_match(token)
        for token in session_journey.split("->")
    }
    
    # We can also check for substring boundaries if zone names include "unit" (e.g., "loreal_unit")
    # but exact token matching or bounded matching is safest.
    for token in journey_tokens:
        if normalized_brand in token and len(normalized_brand) >= 3:
            # Simple bounded check: if the brand is inside the zone token (e.g., 'loreal' in 'lorealunit')
            # we accept it, but reject tiny false positives.
            if token == normalized_brand or token.startswith(normalized_brand):
                return 1.0
                
    return 0.0


def compute_match_score(
    queue_time: datetime, 
    pos_time: datetime, 
    affinity_score: float
) -> float:
    """
    Calculates the probabilistic match score using a weighted ensemble of
    Gaussian temporal decay and spatial brand affinity.
    """
    time_delta = abs((pos_time - queue_time).total_seconds())
    
    # Hard reject to save compute on massive time gaps
    if time_delta > 300:
        return 0.0

    temporal_score = math.exp(- (time_delta ** 2) / (2 * (TIME_VARIANCE_SECONDS ** 2)))
    
    # Calculate explicit ensemble score
    final_score = (WEIGHT_TEMPORAL * temporal_score) + (WEIGHT_AFFINITY * affinity_score)
    
    return min(final_score, 1.0)


def run_correlation_engine(db: DBSession, store_id: str, window_minutes: int = 15) -> int:
    """
    Executes the Bipartite Matching algorithm.
    Finds recent POS transactions and unmapped CV sessions, scores all combinations, 
    and assigns them greedily to maximize system accuracy.
    """
    time_threshold = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    
    # 1. Fetch unmapped POS transactions
    unmapped_tx_stmt = (
        select(Transaction)
        .where(
            and_(
                Transaction.store_id == store_id,
                Transaction.session_id.is_(None),
                Transaction.timestamp >= time_threshold
            )
        )
    )
    transactions = db.execute(unmapped_tx_stmt).scalars().all()
    if not transactions:
        return 0
        
    # 2. Fetch recent candidate video sessions
    recent_sessions_stmt = (
        select(SessionModel)
        .where(
            and_(
                SessionModel.store_id == store_id,
                SessionModel.end_time >= time_threshold,
                SessionModel.is_converted == False
            )
        )
    )
    sessions = db.execute(recent_sessions_stmt).scalars().all()
    if not sessions:
        return 0

    # 3. Pre-cache Queue Completion Times to prevent N+1 query explosion
    session_ids = [sess.session_id for sess in sessions]
    queue_events_stmt = (
        select(Event)
        .where(
            and_(
                Event.session_id.in_(session_ids),
                Event.event_type == "queue_completed"
            )
        )
        .order_by(Event.event_timestamp.desc())  # Explicitly grab the latest event first
    )
    queue_events = db.execute(queue_events_stmt).scalars().all()
    
    queue_time_cache: Dict[str, datetime] = {}
    for ev in queue_events:
        # Prevent fragile overwrites, respect the desc() ordering
        if ev.session_id not in queue_time_cache:
            queue_time_cache[ev.session_id] = ev.event_timestamp

    # 4. Build the scoring matrix
    scoring_matrix: List[Tuple[float, str, str]] = [] 
    
    for tx in transactions:
        for sess in sessions:
            q_time = queue_time_cache.get(sess.session_id)
            
            # Fallback: if no queue event, anchor to session exit time
            anchor_time = q_time if q_time else sess.end_time
            if not anchor_time:
                continue
                
            affinity_score = calculate_brand_affinity(tx.brand_name, sess.journey_path)
            score = compute_match_score(anchor_time, tx.timestamp, affinity_score)
            
            if score >= MATCH_CONFIDENCE_THRESHOLD:
                scoring_matrix.append((score, tx.order_id, sess.session_id))

    # 5. Greedy Bipartite Assignment
    scoring_matrix.sort(key=lambda x: x[0], reverse=True)
    
    assigned_tx_ids = set()
    assigned_session_ids = set()
    matches_made = 0
    
    for score, tx_id, sess_id in scoring_matrix:
        if tx_id in assigned_tx_ids or sess_id in assigned_session_ids:
            continue
            
        tx = db.execute(select(Transaction).where(Transaction.order_id == tx_id)).scalar_one()
        tx.session_id = sess_id
        
        mark_session_converted(db, sess_id)
        
        assigned_tx_ids.add(tx_id)
        assigned_session_ids.add(sess_id)
        matches_made += 1
        
        logger.info(f"Correlated TX {tx_id} to Session {sess_id} [Confidence: {score:.2f}]")
        
    try:
        db.commit()
    except Exception as e:
        logger.error(f"Database error during correlation commit: {str(e)}")
        db.rollback()
        raise
        
    return matches_made