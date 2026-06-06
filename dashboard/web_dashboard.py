import streamlit as st
import requests
from datetime import datetime

# Configuration
# IMPORTANT: When viewing this on the live Render URL, 'localhost' will not work 
# because your browser will try to look for the stream on your personal computer.
# You must change this to your actual backend Render URL (e.g., "https://api-app.onrender.com/api/v1/stores")
API_BASE = "http://localhost:8000/api/v1/stores"

# Set up the Chrome page layout
st.set_page_config(page_title="Purplle Live Dashboard", page_icon="🛍️", layout="wide")
st.title("🛍️ Purplle Store Intelligence")

# ==========================================
# 🎛️ SIDEBAR CONTROL PANEL
# ==========================================
st.sidebar.image("https://media6.ppl-media.com/mediafiles/ecomm/promo/1728010486_purplle-logo.svg", width=150)
st.sidebar.header("Control Panel")

# 1. Select Store
selected_store = st.sidebar.selectbox("📍 Select Store", ["STORE_BLR_001", "STORE_BLR_002"])

# 2. Select Camera (Dynamic list based on the store chosen)
if selected_store == "STORE_BLR_002":
    camera_options = ["All Cameras", "CAM_ENTRY_01", "CAM_ENTRY_02", "CAM_SKINCARE_01", "CAM_CHECKOUT_01"]
else:
    camera_options = ["All Cameras", "CAM_ENTRY_01", "CAM_ZONE_01","CAM_ZONE_02", "CAM_CHECKOUT_01"]

selected_camera = st.sidebar.selectbox("🎥 Select Camera", camera_options)

st.sidebar.divider()
st.sidebar.caption("🟢 API Status: Connected")
st.sidebar.caption("🟢 Pipeline: Streaming")

# ==========================================
# 🎥 VIDEO FEED AREA
# ==========================================
if selected_camera == "All Cameras":
    st.markdown(f"**Live Monitoring:** Store `{selected_store}` | Aggregate View")
    st.info("Select a specific camera from the sidebar to view the live video feed.")
else:
    st.markdown(f"**Live Monitoring:** Store `{selected_store}` | Camera Feed: `{selected_camera}`")
    
    # Map the UI selection dynamically to the new streaming endpoint in main.py
    video_url = f"{API_BASE}/{selected_store}/cameras/{selected_camera}/stream"
    
    # Embedded video player (outside the refresh fragment so it doesn't flicker)
    st.video(video_url, autoplay=True, loop=True, muted=True)

st.divider()

# ==========================================
# 📊 MAIN DASHBOARD AREA (Auto-Refreshing)
# ==========================================

# @st.fragment isolates this function so ONLY the metrics reload every 2 seconds. 
# The rest of the page (including the video stream) stays smooth and uninterrupted.
@st.fragment(run_every=2)
def live_metrics_dashboard():
    try:
        # Prepare the query parameters
        params = {}
        if selected_camera != "All Cameras":
            params["camera_id"] = selected_camera

        # Fetch data from your API
        metrics_res = requests.get(f"{API_BASE}/{selected_store}/metrics", params=params, timeout=2)
        funnel_res = requests.get(f"{API_BASE}/{selected_store}/funnel", params=params, timeout=2)
        
        metrics = metrics_res.json() if metrics_res.status_code == 200 else None
        funnel = funnel_res.json() if funnel_res.status_code == 200 else None
        
        st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
        
        if metrics:
            st.subheader("📊 Real-Time Metrics")
            col1, col2, col3, col4, col5 = st.columns(5)
            
            col1.metric(label="Unique Visitors", value=metrics.get("total_unique_visitors", 0))
            col2.metric(label="Converted", value=metrics.get("converted_visitors", 0))
            col3.metric(label="Conversion Rate", value=f"{metrics.get('real_time_conversion_rate', 0.0)}%")
            col4.metric(label="Queue Depth", value=metrics.get("active_queue_depth", 0))
            col5.metric(label="Avg Wait (sec)", value=metrics.get("average_wait_time_seconds", 0.0))
            
            st.divider()
            
        if funnel and "funnel_stages" in funnel:
            st.subheader("🔽 Live Conversion Funnel")
            
            for stage in funnel["funnel_stages"]:
                colA, colB = st.columns([1, 4])
                pct = stage['conversion_percentage']
                
                with colA:
                    st.markdown(f"**{stage['stage_name']}**<br/>{stage['visitor_count']} visitors", unsafe_allow_html=True)
                with colB:
                    bar_val = max(0.0, min(1.0, pct / 100.0))
                    st.progress(bar_val, text=f"{pct}% Conversion")
        
        if not metrics and not funnel:
            st.warning(f"⚠️ Connected to API, but no metrics found for {selected_camera}. Start the CV pipeline!")
                
    except requests.exceptions.RequestException:
        st.error("🚨 Cannot connect to API. Is FastAPI running in the background?")

# Trigger the isolated loop
live_metrics_dashboard()