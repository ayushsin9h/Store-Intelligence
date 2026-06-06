# pipeline/tracker.py

import logging
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
import cv2
import numpy as np

from pipeline.emit import TelemetryBroker

def is_billing_zone(zone_id: str) -> bool:
    """Helper to identify billing zones for queue metrics."""
    return "billing" in zone_id.lower() or "checkout" in zone_id.lower() or "cash" in zone_id.lower()

logger = logging.getLogger(__name__)

class TrackingStateManager:
    """
    Translates raw bounding box coordinates into semantic business events.
    Handles occlusion, zone transitions, and queue intent analytics.
    """
    def __init__(
        self, 
        broker: TelemetryBroker, 
        store_id: str, 
        camera_id: str,
        store_zones: Dict[str, List[Tuple[float, float]]],
        max_lost_frames: int = 15
    ):
        self.broker = broker
        self.store_id = store_id
        self.camera_id = camera_id
        
        self.store_zones = {
            z_id: np.array(coords, dtype=np.int32) 
            for z_id, coords in store_zones.items()
        }
        self.max_lost_frames = max_lost_frames
        
        # State Memory
        self.tracks: Dict[int, Dict[str, Any]] = {}

    def _get_footprint_coordinate(self, box: List[float]) -> Tuple[float, float]:
        """Extracts the bottom-center of the bounding box where feet touch the floor."""
        x1, y1, x2, y2 = box
        center_x = (x1 + x2) / 2.0
        return (center_x, float(y2))

    def _resolve_zone(self, x: float, y: float) -> Optional[str]:
        """Uses OpenCV C++ backend to check point-in-polygon."""
        pt = (float(x), float(y))
        for zone_id, polygon in self.store_zones.items():
            if cv2.pointPolygonTest(polygon, pt, measureDist=False) >= 0:
                return zone_id
        return None

    def update(self, current_tracks: List[Dict[str, Any]], frame_timestamp: datetime):
        """Processes current frame tracks and emits business state changes."""
        current_frame_ids = set()
        iso_time = frame_timestamp.isoformat()

        for track in current_tracks:
            t_id = track["track_id"]
            box = track["box"] # These are pre-scaled by detect.py!
            confidence = track.get("confidence", 0.0)
            
            visitor_id = f"V_{self.camera_id}_{t_id}"
            current_frame_ids.add(t_id)
            
            x, y = self._get_footprint_coordinate(box)
            current_zone = self._resolve_zone(x, y)

            # --- 1. ENTRY ---
            if t_id not in self.tracks:
                self.tracks[t_id] = {
                    "zone": None, 
                    "miss_count": 0, 
                    "active": True,
                    "zone_enter_time": None,     # ADDED: Tracks general browse time
                    "billing_enter_time": None   # Keeps strict queue tracking separate
                }
                self.broker.emit(
                    event_type="ENTRY", store_id=self.store_id, camera_id=self.camera_id,
                    visitor_id=visitor_id, event_time=iso_time, confidence=confidence
                )

            state = self.tracks[t_id]
            if not state["active"]:
                state["active"] = True
                state["miss_count"] = 0

            # --- 2. ZONE & QUEUE TRANSITIONS ---
            previous_zone = state["zone"]
            
            if current_zone != previous_zone:
                # Handle Exit from previous zone
                if previous_zone is not None:
                    # Calculate general dwell time for the zone being exited
                    zone_enter_ts = state.get("zone_enter_time")
                    zone_dwell_ms = 0
                    if zone_enter_ts:
                        zone_dwell_ms = int((frame_timestamp - zone_enter_ts).total_seconds() * 1000)

                    # Queue Analytics Check
                    if is_billing_zone(previous_zone):
                        bill_enter_ts = state.get("billing_enter_time")
                        if bill_enter_ts:
                            duration = (frame_timestamp - bill_enter_ts).total_seconds()
                            if duration > 15.0: # Assumes true checkout attempt
                                self.broker.emit(
                                    event_type="QUEUE_COMPLETED", store_id=self.store_id,
                                    camera_id=self.camera_id, visitor_id=visitor_id,
                                    event_time=iso_time, zone_id=previous_zone, 
                                    wait_seconds=int(duration), dwell_ms=int(duration * 1000)
                                )
                            else: # Abandoned queue / walk-through
                                self.broker.emit(
                                    event_type="BILLING_QUEUE_ABANDON", store_id=self.store_id,
                                    camera_id=self.camera_id, visitor_id=visitor_id,
                                    event_time=iso_time, zone_id=previous_zone, 
                                    wait_seconds=int(duration), dwell_ms=int(duration * 1000)
                                )
                        state["billing_enter_time"] = None

                    self.broker.emit(
                        event_type="ZONE_EXIT", store_id=self.store_id, camera_id=self.camera_id,
                        visitor_id=visitor_id, event_time=iso_time, zone_id=previous_zone,
                        dwell_ms=zone_dwell_ms
                    )
                
                # Handle Enter to new zone
                if current_zone is not None:
                    state["zone_enter_time"] = frame_timestamp
                    if is_billing_zone(current_zone):
                        state["billing_enter_time"] = frame_timestamp
                        
                    self.broker.emit(
                        event_type="ZONE_ENTER", store_id=self.store_id, camera_id=self.camera_id,
                        visitor_id=visitor_id, event_time=iso_time, zone_id=current_zone,
                        zone_hotspot_x=x, zone_hotspot_y=y, confidence=confidence
                    )
                
                state["zone"] = current_zone

        # --- 3. OCCLUSION & EXIT HANDLING ---
        missing_ids = set(self.tracks.keys()) - current_frame_ids
        for t_id in list(missing_ids):
            state = self.tracks[t_id]
            if not state["active"]:
                continue
                
            state["miss_count"] += 1
            if state["miss_count"] > self.max_lost_frames:
                visitor_id = f"V_{self.camera_id}_{t_id}"
                
                if state["zone"] is not None:
                    # Calculate final dwell times before exit
                    zone_enter_ts = state.get("zone_enter_time")
                    zone_dwell_ms = 0
                    if zone_enter_ts:
                        zone_dwell_ms = int((frame_timestamp - zone_enter_ts).total_seconds() * 1000)

                    if is_billing_zone(state["zone"]):
                        bill_enter_ts = state.get("billing_enter_time")
                        if bill_enter_ts:
                            duration = (frame_timestamp - bill_enter_ts).total_seconds()
                            if duration > 8.0:
                                self.broker.emit(
                                    event_type="QUEUE_COMPLETED", store_id=self.store_id,
                                    camera_id=self.camera_id, visitor_id=visitor_id,
                                    event_time=iso_time, zone_id=state["zone"], 
                                    wait_seconds=int(duration), dwell_ms=int(duration * 1000)
                                )
                            else:
                                self.broker.emit(
                                    event_type="BILLING_QUEUE_ABANDON", store_id=self.store_id,
                                    camera_id=self.camera_id, visitor_id=visitor_id,
                                    event_time=iso_time, zone_id=state["zone"], 
                                    wait_seconds=int(duration), dwell_ms=int(duration * 1000)
                                )
                            state["billing_enter_time"] = None
                            
                    self.broker.emit(
                        event_type="ZONE_EXIT", store_id=self.store_id, camera_id=self.camera_id,
                        visitor_id=visitor_id, event_time=iso_time, zone_id=state["zone"],
                        dwell_ms=zone_dwell_ms
                    )
                
                self.broker.emit(
                    event_type="EXIT", store_id=self.store_id, camera_id=self.camera_id,
                    visitor_id=visitor_id, event_time=iso_time
                )
                
                # Free memory completely
                del self.tracks[t_id]