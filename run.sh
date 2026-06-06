#!/bin/bash

# 1. Create the data directory so SQLite has a place to live
mkdir -p data

# 2. Start the FastAPI backend in the background on a fixed internal port (8000)
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# 3. Wait a few seconds for the API to boot up
sleep 3 

# 4. Start Streamlit in the foreground, pointing to the dashboard folder
streamlit run dashboard/web_dashboard.py --server.port $8501 --server.address 0.0.0.0