# System Architecture & Design

## 1. High-Level Overview
The Store Intelligence Platform is designed as a decoupled, microservice-inspired architecture split into two distinct environments: the **Edge CV Pipeline** (The "Eyes") and the **Intelligence API** (The "Brain"). 

By decoupling the heavy, GPU-bound computer vision tasks from the I/O-bound web server, the system mimics real-world enterprise retail deployments. The edge nodes process CCTV feeds locally, generate lightweight semantic JSON events, and stream them to the cloud via HTTP over the internet.

## 2. Pipeline Flow
1. **Detection & Tracking (Edge):** Raw video is processed using YOLOv8 for human detection and ByteTrack for multi-object tracking. The spatial coordinates are mapped against polygons defined in `store_layout.json`.
2. **State Management (Edge):** A `TrackingStateManager` interprets raw bounding boxes into business logic (e.g., waiting 15 seconds in the billing zone triggers a `queue_completed` state).
3. **Telemetry Ingestion (Cloud):** The FastAPI `/ingest` endpoint receives batches of events. It relies on Pydantic for strict schema validation and deduplicates requests using `event_id`.
4. **Session & Correlation Engine (Cloud):** The backend stitches discrete events into continuous `journey_path` strings (e.g., `ENTRY -> SKINCARE -> CHECKOUT -> EXIT`). A bipartite matching engine correlates POS transactions to video sessions based on a 5-minute trailing window and brand-affinity scoring.
5. **OLAP Cache (Cloud):** Heavy spatial math (heatmaps) and full-table scans (funnels) are intercepted by `olap_cache.py`, an in-memory TTL caching layer, protecting the SQLite database from frontend dashboard polling.
6. **Media Streaming & UI (Cloud to Client):** Because hosting live GPU inference on a free-tier cloud is financially unviable, the edge pipeline generates annotated `.mp4` files alongside the telemetry. The FastAPI server utilizes HTTP Range Requests (`StreamingResponse`) to chunk these media files efficiently to the Streamlit frontend, maintaining a smooth HTML5 video feed while strictly respecting the 512MB memory limits of the deployment container.

## 3. AI-Assisted Decisions
As required by the AI Policy, I collaborated extensively with an LLM (Google Gemini) to accelerate boilerplate generation, stress-test my architecture, and refine edge cases.

* **Instance 1: SQLite Threading & Testing (Overridden)**
    * *AI Suggestion:* The LLM generated a standard Pytest suite using FastAPI's `TestClient` and an in-memory SQLite database (`sqlite:///:memory:`).
    * *My Override:* I recognized that FastAPI opens multiple threaded sessions during request handling, which causes in-memory SQLite to spawn disconnected, empty databases. I overrode the AI's design by explicitly forcing SQLAlchemy's `StaticPool` to ensure the test assertions and the API hit the exact same database instance.
* **Instance 2: Schema Strictness & Idempotency (Collaborative Refinement)**
    * *AI Suggestion:* The LLM initially drafted Pythonic, lowercase event enums (e.g., `entry`, `zone_entered`) and relied on Pydantic's `extra="ignore"` configuration to parse incoming JSON payloads.
    * *My Override/Refinement:* I realized this violated the strict Event Catalogue mandated by the challenge rubric. Furthermore, I caught a critical bug: because `event_id` wasn't explicitly declared in the Pydantic model, it was being silently dropped, destroying the idempotency logic. I prompted the AI to rewrite the entire pipeline to enforce strict uppercase strings (`BILLING_QUEUE_JOIN`) and inject the explicit `event_id` into the schema to guarantee mathematical deduplication.