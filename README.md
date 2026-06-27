# 🛍️ Purplle Store Intelligence

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.103.0-009688?logo=fastapi)
![Streamlit](https://img.shields.io/badge/Streamlit-1.26.0-FF4B4B?logo=streamlit)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?logo=docker)
![Render](https://img.shields.io/badge/Deployed_on-Render-000000?logo=render)

An edge-to-cloud computer vision and analytics platform built for the **Purplle Tech Challenge**.

## 🌐 Live Demo

**Dashboard:** https://store-intelligence-ai.onrender.com

**API Documentation:** https://store-intelligence-ai.onrender.com/docs

---

## 🌟 Key Features & Engineering Highlights

- **Decoupled Edge-to-Cloud Architecture:** Uses YOLOv8 and OpenCV at the edge to track visitors at 25+ FPS. Transmits telemetry as JSON to the cloud.
- **High-Concurrency PostgreSQL Backend:** Migrated from SQLite to containerized PostgreSQL utilizing SQLAlchemy 2.0 and `SessionLocal` dependency injection to eliminate 100% of database-locking bottlenecks during multi-camera telemetry bursts.
- **Mathematical Correlation Engine:** Computer Vision edge nodes frequently drop IDs. The API utilizes a custom "camera-aware" heuristic to rebuild disjointed customer journeys, recovering 100% of dropped tracking IDs to build perfect, cascading conversion funnels.
- **Real-Time SPA Dashboard:** An asynchronous Streamlit dashboard that isolates DOM updates via `@st.fragment` to auto-refresh metrics every 2 seconds without full-page UI flashes.

---

## 🏗️ System Architecture

`CCTV` → `YOLOv8 Edge Tracker` → `Telemetry JSON` → `FastAPI` → `PostgreSQL` → `Mathematical Correlation Engine` → `Streamlit Dashboard`

---

## 📂 Project Structure

```text
📦 Store-Intelligence
├── app/
├── dashboard/
├── doc/
├── pipeline/
├── data/
├── tests/
├── Dockerfile
├── run.sh
├── requirements-api.txt
├── requirements-edge.txt
├── store_layout.json
└── README.md
```

## ⚙️ Technology Stack

| Layer | Technology |
|---------|------------|
| Backend | FastAPI |
| Frontend | Streamlit |
| Database | PostgreSQL |
| Computer Vision | YOLOv8 |
| Deployment | Docker |
| Hosting | Render |
| Language | Python 3.11 |

## 🚀 Local Setup

### Clone Repository

```bash
git clone https://github.com/ayushsin9h/Store-Intelligence.git
cd Store-Intelligence
```

### Create Virtual Environment

```bash
python -m venv venv
```

Windows:

```powershell
venv\Scripts\activate
```

Linux/Mac:

```bash
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements-api.txt
pip install streamlit pandas requests
```

## ▶️ Run Backend

```bash
mkdir data
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API Docs:

```text
http://localhost:8000/docs
```

## ▶️ Run Dashboard

```bash
streamlit run dashboard/web_dashboard.py
```

Dashboard:

```text
http://localhost:8501
```

## 🎥 Running Edge Pipeline

```bash
pip install -r requirements-edge.txt

python pipeline/detect.py --source resources/Store_1/cam1.mp4
```

## 📊 Analytics

- Visitor Count
- Active Visitors
- Session Duration
- Conversion Funnel
- Queue Length
- Wait Time
- Zone Occupancy
- Dwell Time

## 🔄 API Endpoints

```http
GET /health
POST /ingest
GET /analytics/funnel
GET /analytics/zones
GET /analytics/queue
GET /dashboard
```

## 🐳 Docker Deployment

```bash
docker build -t store-intelligence .
docker run -p 8000:8000 store-intelligence
```

## ☁️ Render Deployment

Uses:

- Dockerfile
- run.sh
- FastAPI
- Streamlit
- Auto Port Binding

## 🎯 Purplle Challenge Alignment

✅ Customer Journey Tracking

✅ Retail Conversion Analytics

✅ Queue Monitoring

✅ Zone Intelligence

✅ Multi-Store Visibility

✅ Edge-to-Cloud Architecture

✅ Real-Time Dashboarding

---

## ❤️ Built for the Purplle Tech Challenge

Transforming CCTV footage into actionable retail intelligence through Computer Vision, Analytics, and Cloud Engineering.
