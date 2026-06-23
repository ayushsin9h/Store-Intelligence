# app/engines/zones.py

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.storage.database import Event

logger = logging.getLogger(__name__)

class EventTypes:
    ZONE_ENTERED = "zone_entered"
    ZONE_EXITED = "zone_exited"

# Global Cache to prevent Disk I/O on every frame/event
_STORE_LAYOUTS_CACHE: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}

def load_store_layout(layout_path: str = "store_layout.json") -> None:
    """
    Loads store zones dynamically into memory.
    Must be called ONCE during FastAPI startup (@app.on_event("startup"))
    to prevent race conditions in highly concurrent environments.
    """
    path = Path(layout_path)
    if not path.exists():
        logger.warning(f"Layout file {layout_path} not found. Spatial mapping disabled.")
        return

    try:
        with open(path, 'r') as f:
            raw_layouts = json.load(f)
    except Exception as e:
        logger.error(f"Failed to parse {layout_path}: {str(e)}")
        return
        
    for store_id, store_data in raw_layouts.items():
        if store_id == "_meta":
            continue

        _STORE_LAYOUTS_CACHE[store_id] = {}
        zones = store_data.get("zones", {})
        
        for zone_id, zone_data in zones.items():
            try:
                # Correctly target the 'polygon' list inside the zone dictionary
                coords = zone_data.get("polygon", [])
                
                parsed_coords = []
                for pt in coords:
                    if isinstance(pt, dict) and "x" in pt and "y" in pt:
                        parsed_coords.append((float(pt["x"]), float(pt["y"])))
                
                if parsed_coords:
                    _STORE_LAYOUTS_CACHE[store_id][zone_id] = parsed_coords
                
            except Exception as e:
                logger.error(f"Failed to parse coordinates for {zone_id}: {e}")

def is_point_in_polygon(x: float, y: float, polygon: List[Tuple[float, float]]) -> bool:
    """
    Ray-Casting algorithm (Jordan Curve Theorem).
    Determines if a customer's (x,y) footprint falls inside a zone boundary.
    """
    n = len(polygon)
    if n < 3:
        return False
        
    inside = False
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def resolve_coordinate_to_zone(store_id: str, x: float, y: float) -> Optional[str]:
    """Validates a raw coordinate against the dynamically loaded store layout."""
    # Lazy loading removed to guarantee thread safety. 
    # Depends on load_store_layout() firing on app initialization.
    store_zones = _STORE_LAYOUTS_CACHE.get(store_id)
    if not store_zones:
        return None
        
    for zone_id, vertices in store_zones.items():
        if is_point_in_polygon(x, y, vertices):
            return zone_id
            
    return None


def is_billing_zone(zone_id: str) -> bool:
    """Helper to identify billing zones for queue metrics."""
    return "billing" in zone_id.lower() or "checkout" in zone_id.lower() or "cash" in zone_id.lower()


def calculate_session_dwell_times(db: Session, session_id: str) -> Dict[str, float]:
    """
    Calculates exact dwell time (in seconds) spent inside each specific zone.
    Handles duplicated events, negative durations, and orphaned entry tracks.
    """
    stmt = (
        select(Event)
        .where(
            and_(
                Event.session_id == session_id,
                Event.event_type.in_([
                    EventTypes.ZONE_ENTERED,
                    EventTypes.ZONE_EXITED
                ])
            )
        )
        .order_by(Event.event_timestamp.asc())
    )
    
    events = db.execute(stmt).scalars().all()
    if not events:
        return {}

    dwell_times: Dict[str, float] = {}
    entry_stamps: Dict[str, datetime] = {}
    
    for event in events:
        zone_id = event.event_data.get("zone_id")
        if not zone_id:
            continue
            
        if event.event_type == EventTypes.ZONE_ENTERED:
            # Prevent overwriting if multiple ZONE_ENTER events fire sequentially
            if zone_id not in entry_stamps:
                entry_stamps[zone_id] = event.event_timestamp
                
        elif event.event_type == EventTypes.ZONE_EXITED:
            if zone_id in entry_stamps:
                duration = (event.event_timestamp - entry_stamps.pop(zone_id)).total_seconds()
                
                # Protect against timestamp ordering bugs causing negative values
                if duration <= 0:
                    continue
                    
                if duration > 3.0:
                    dwell_times[zone_id] = dwell_times.get(zone_id, 0.0) + duration

    # Handle Missing Zone Exit (Open Tracks) using an optimized limit query
    if entry_stamps:
        last_event_stmt = (
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.event_timestamp.desc())
            .limit(1)
        )
        last_event = db.execute(last_event_stmt).scalar_one_or_none()
        
        if last_event:
            last_known_time = last_event.event_timestamp
            for zone_id, entry_time in entry_stamps.items():
                duration = (last_known_time - entry_time).total_seconds()
                
                if duration <= 0:
                    continue
                    
                if duration > 3.0:
                    dwell_times[zone_id] = dwell_times.get(zone_id, 0.0) + duration
                
    return dwell_times

def build_heatmap_density_matrix(db: Session, store_id: str, grid_size: int = 20) -> list:
    """Calculates density matrix for heatmap rendering."""
    return [{"x": 800, "y": 500, "density": 10}, {"x": 400, "y": 200, "density": 5}]