# 🛍️ Purplle Store Intelligence

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.103.0-009688?logo=fastapi)
![Streamlit](https://img.shields.io/badge/Streamlit-1.26.0-FF4B4B?logo=streamlit)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?logo=docker)
![Render](https://img.shields.io/badge/Deployed_on-Render-000000?logo=render)

An edge-to-cloud computer vision and analytics platform built for the **Purplle Tech Challenge**.

## 🌐 Live Demo

**Dashboard:** https://store-intelligence-s5l9.onrender.com

**API Documentation:** https://store-intelligence-s5l9.onrender.com/docs

---

## 🌟 Key Features

- Real-Time Retail Intelligence Dashboard
- Customer Journey Analytics
- Conversion Funnel Analysis
- Queue Intelligence
- Edge AI Powered (YOLOv8 + Tracking)
- Cloud-Native Deployment
- FastAPI Backend + Streamlit Frontend
- Dockerized Deployment on Render

---

## 🏗️ System Architecture

CCTV → YOLOv8 → Tracking → Zone Mapping → Event Generation → FastAPI → Analytics Engine → Streamlit Dashboard

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
| Database | SQLite |
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

## 👨‍💻 Author

**Ayush Singh**

Microsoft Student Ambassador

GitHub: https://github.com/ayushsin9h

LinkedIn: https://linkedin.com/in/ayushsin9h

---

## ❤️ Built for the Purplle Tech Challenge

Transforming CCTV footage into actionable retail intelligence through Computer Vision, Analytics, and Cloud Engineering.
