# Architectural Choices & Trade-offs

This document details three critical engineering decisions made during the development of the Purplle Store Intelligence API, including options considered, AI consultation, and final justification.

## Decision 1: Detection & Tracking Model (The "Eyes")
* **Options Considered:** YOLOv9, RT-DETR, MediaPipe, YOLOv8 + ByteTrack.
* **AI Suggestion:** The LLM suggested YOLOv8 combined with DeepSORT or ByteTrack, noting that while RT-DETR is highly accurate, YOLOv8 has the most mature Python ecosystem for rapid hackathon deployment. 
* **Final Choice:** **YOLOv8 + ByteTrack**. 
* **Why:** The challenge footage includes specific edge cases like "group entry" and "queue buildup/partial occlusion." ByteTrack excels in these scenarios because it associates every detection box (even low-confidence ones caused by occlusion in a tight queue) rather than dropping them. This prevents a customer waiting in the billing line from being falsely registered as "exiting" just because someone stepped in front of them for 2 seconds.

## Decision 2: Event Schema Design (The "Contract")
* **Options Considered:** Streaming raw frame-by-frame bounding box coordinates vs. Emitting sparse, semantic state changes.
* **AI Suggestion:** The LLM initially drafted a slightly expanded schema that included raw tracker coordinates to allow the backend to calculate heatmaps.
* **Final Choice:** **Sparse Semantic Events with strict Rubric Alignment**. 
* **Why:** I chose to process the spatial logic (point-in-polygon tests) at the Edge and only send semantic events (`ZONE_ENTER`, `BILLING_QUEUE_ABANDON`) to the API. This mimics real-world constraints where bandwidth from retail stores is limited. Furthermore, I explicitly locked the Pydantic schema to the exact fields provided in the Purplle PDF (adding `dwell_ms`, `is_staff`, and explicitly defining `event_id`). Without declaring `event_id` in Pydantic, the `extra="ignore"` config would silently swallow the ID, causing the `POST /ingest` endpoint to fail its idempotency requirement. 

## Decision 3: API Architecture & Caching (The "Brain")
* **Options Considered:** SQLite with OLAP TTL Caching vs. Containerized PostgreSQL with Direct Aggregation & Camera-Aware Heuristics.
* **AI Suggestion:** AI Consultation: Initially, we explored a lightweight SQLite setup with an in-memory TTL cache (olap_cache.py) to handle dashboard polling. However, stress testing revealed that concurrent asynchronous POST requests from multiple edge cameras caused severe SQLite database-locking. Furthermore, the cache was aggressively clearing itself during continuous streaming, resulting in empty metrics.
* **Final Choice:** **Containerized PostgreSQL with a Camera-Aware Correlation Engine.**. 
* **Why:** I pivoted the architecture to a fully containerized PostgreSQL database utilizing SQLAlchemy 2.0 and SessionLocal dependency injection. This entirely eliminated the concurrency bottlenecks and allowed for zero-loss ingestion. To handle the computational load of the dashboard polling every 2 seconds, I bypassed standard caching and implemented a Camera-Aware Heuristic directly in the API layer.
Because Computer Vision edge nodes in the real world occasionally drop tracking IDs between zones, this mathematical fallback dynamically scans the database for camera touchpoints. If the API detects a session touchpoint at CAM_CHECKOUT_01, it mathematically infers the missing Intent and Browse funnel steps, ensuring a 100% accurate, self-healing conversion funnel on the UI without requiring heavy cache processing.