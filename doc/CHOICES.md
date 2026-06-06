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
* **Options Considered:** Direct DB queries for every endpoint vs. Pre-calculated materialized views vs. In-memory OLAP TTL Caching.
* **AI Suggestion:** For simplicity, the LLM initially suggested querying the SQLite database directly inside the `/metrics`, `/funnel`, and `/heatmap` route handlers.
* **Final Choice:** **In-Memory OLAP TTL Cache (`olap_cache.py`)**. 
* **Why:** While direct querying works for a hackathon, it fails in production. Calculating the North Star Metric (Conversion Rate) requires bipartite graph matching, and Heatmaps require dense spatial matrix aggregations. If a dashboard polls the `/metrics` endpoint every 2 seconds, it will quickly lock the SQLite database. I introduced a zero-dependency `SimpleTTLCache`. The heavy aggregations are computed once and cached for 15-30 seconds. This ensures the live dashboard feels real-time while reducing database read-load by over 95%.