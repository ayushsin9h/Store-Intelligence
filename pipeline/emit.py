# pipeline/emit.py

import os
import logging
import uuid
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

import requests
import json

def log_event_to_jsonl(event_data, filename="submission_events.jsonl"):
    """
    Appends a single event dictionary to a JSONL file.
    """
    with open(filename, 'a') as file:
        file.write(json.dumps(event_data) + '\n')

logger = logging.getLogger(__name__)

class TelemetryBroker:
    """
    Non-blocking, micro-batching telemetry emitter.
    Protects the inference loop from network I/O latency and ensures 
    state consistency via periodic background flushing.
    """
    def __init__(
        self, 
        endpoint_url: str = None, 
        batch_size: int = 25,
        flush_interval_seconds: float = 3.0
    ):
        self.endpoint_url = endpoint_url or os.getenv(
            "INGEST_API_URL", 
            "http://localhost:8000/api/v1/events/ingest"
        )
        self.batch_size = batch_size
        self.buffer: List[Dict[str, Any]] = []
        
        # Thread safety locks
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2)
        
        # Edge-State Cache
        self._active_zones: Dict[str, str] = {}

        self._flush_interval = flush_interval_seconds
        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
        self._flush_thread.start()

    def _periodic_flush(self):
        """Background daemon that guarantees events are dispatched even if the batch isn't full."""
        while not self._stop_event.wait(self._flush_interval):
            self.flush()

    def flush(self):
        """Forces a flush of the current memory buffer to the backend API."""
        should_flush = False
        payload_copy = []
        
        with self._lock:
            if self.buffer:
                payload_copy = self.buffer.copy()
                self.buffer.clear()
                should_flush = True
                
        if should_flush:
            self._executor.submit(self._dispatch_network, payload_copy)

    def emit(self, event_type: str, store_id: str, camera_id: str, visitor_id: str, **kwargs):
        """Ingests a raw tracking event, deduplicates zone spam, and queues it."""
        
        if not visitor_id:
            visitor_id = f"anon_{uuid.uuid4().hex[:8]}"

        event_time = kwargs.pop("event_time", datetime.now(timezone.utc).isoformat())

        # 1. Edge Deduplication & State Management (UPDATED TO STRICT SCHEMA)
        if event_type == "ZONE_ENTER":
            zone_id = kwargs.get("zone_id")
            if not zone_id:
                return
                
            with self._lock:
                if self._active_zones.get(visitor_id) == zone_id:
                    return  # Suppress duplicate emission
                self._active_zones[visitor_id] = zone_id
                
        elif event_type == "ZONE_EXIT":
            with self._lock:
                zone_id = kwargs.get("zone_id")
                if self._active_zones.get(visitor_id) == zone_id:
                    self._active_zones.pop(visitor_id, None)

        elif event_type in ["EXIT", "QUEUE_COMPLETED", "BILLING_QUEUE_ABANDON"]:
            with self._lock:
                self._active_zones.pop(visitor_id, None)

        # 2. Payload Construction
        event_payload = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_time": event_time,
            **kwargs  
        }
        
        # Log to local file for offline validation/debugging
        log_event_to_jsonl(event_payload)
        
        # 3. Buffer Management
        should_flush = False
        payload_copy = []
        
        with self._lock:
            self.buffer.append(event_payload)
            # UPDATED TO STRICT SCHEMA
            if len(self.buffer) >= self.batch_size or event_type in ["EXIT", "QUEUE_COMPLETED"]:
                payload_copy = self.buffer.copy()
                self.buffer.clear()
                should_flush = True

        if should_flush:
            self._executor.submit(self._dispatch_network, payload_copy)

    def _dispatch_network(self, payload: List[Dict[str, Any]]):
        """Executes the HTTP POST out-of-band to protect inference FPS."""
        if not payload:
            return
            
        try:
            response = requests.post(self.endpoint_url, json=payload, timeout=2.5)
            response.raise_for_status()
            logger.debug(f"Dispatched batch of {len(payload)} events successfully.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Telemetry API dispatch failed: {e}. Dropped {len(payload)} events.")
            
    def shutdown(self):
        """Gracefully halts the background thread and flushes remaining events."""
        self._stop_event.set()
        if self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.0)
            
        self.flush()
        self._executor.shutdown(wait=True)