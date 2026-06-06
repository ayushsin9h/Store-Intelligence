# pipeline/detect.py

import argparse
import logging
import json
import cv2
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

from ultralytics import YOLO

from pipeline.emit import TelemetryBroker
from pipeline.tracker import TrackingStateManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Tactical Hackathon Optimization: 
FRAME_SKIP = 3  

def load_camera_zones(layout_path: str, store_id: str) -> dict:
    """Extracts polygons. Robust against various JSON nesting schemas."""
    path = Path(layout_path)
    if not path.exists():
        logger.warning(f"No layout found at {layout_path}. Running without spatial zones.")
        return {}
        
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw_layouts = json.load(f)
            
        store_data = raw_layouts.get(store_id, {})
        zones = store_data.get("zones", {})
        
        formatted_zones = {}
        for zone_id, coords in zones.items():
            if not coords:
                continue
            polygon_pts = coords.get("polygon", []) 
            formatted_zones[zone_id] = [(float(pt["x"]), float(pt["y"])) for pt in polygon_pts]
            
        logger.info(f"Loaded {len(formatted_zones)} zones for store {store_id}.")
        return formatted_zones
    except Exception as e:
        logger.error(f"Failed to parse zones: {e}")
        return {}

def run_pipeline(
    source: str, store_id: str, camera_id: str, api_url: str,
    layout_path: str, model_weights: str = "yolov8n.pt", show_video: bool = False
):
    logger.info(f"Initializing Store Intelligence Edge Node | Store: {store_id} | Camera: {camera_id}")
    
    broker = TelemetryBroker(endpoint_url=api_url, batch_size=25, flush_interval_seconds=3.0)
    store_zones = load_camera_zones(layout_path, store_id)
    
    state_manager = TrackingStateManager(
        broker=broker, store_id=store_id, camera_id=camera_id,
        store_zones=store_zones, max_lost_frames=15
    )
    
    logger.info(f"Loading YOLO model: {model_weights}")
    model = YOLO(model_weights)
    
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        logger.error(f"Failed to open video source: {source}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps != fps:
        fps = 30.0 
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # --- DYNAMIC SCALING (The Hackathon Saver) ---
    # JSON blueprint is strictly 1920x1080. We must scale YOLO coords to match it.
    scale_x = 1920.0 / width if width > 0 else 1.0
    scale_y = 1080.0 / height if height > 0 else 1.0
    if scale_x != 1.0 or scale_y != 1.0:
        logger.info(f"Applying spatial scaling multiplier: X:{scale_x:.2f}, Y:{scale_y:.2f}")
        
    # --- NEW: Video Writer Setup for Dashboard Streaming ---
    output_dir = os.path.join("data", store_id)
    os.makedirs(output_dir, exist_ok=True)
    output_video_path = os.path.join(output_dir, f"{camera_id}.mp4")
    
    # Switched to avc1 (H.264) for HTML5 Browser Compatibility
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    out_writer = cv2.VideoWriter(output_video_path, fourcc, fps / FRAME_SKIP, (width, height))
    logger.info(f"Exporting annotated video stream to: {output_video_path}")
    # -------------------------------------------------------

    simulated_start_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    frame_idx = 0

    logger.info(f"Starting inference loop on {source} at {fps} FPS (Processing every {FRAME_SKIP} frames)...")
    
    try:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                logger.info("End of video stream reached.")
                break
                
            frame_idx += 1
            if frame_idx % FRAME_SKIP != 0:
                continue
                
            frame_time = simulated_start_time + timedelta(seconds=(frame_idx / fps))
            
            # Tuned conf down slightly for the Nano model to pick up distant shoppers
            results = model.track(
                frame, persist=True, tracker="bytetrack.yaml", 
                classes=[0], conf=0.30, verbose=False
            )
            
            current_tracks = []
            if results[0].boxes is not None and results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.int().cpu().numpy()
                confs = results[0].boxes.conf.cpu().numpy()
                
                for box, t_id, conf in zip(boxes, track_ids, confs):
                    current_tracks.append({
                        "track_id": int(t_id),
                        "box": [
                            float(box[0]) * scale_x,
                            float(box[1]) * scale_y,
                            float(box[2]) * scale_x,
                            float(box[3]) * scale_y
                        ],
                        "confidence": float(conf)
                    })
                    
            state_manager.update(current_tracks, frame_time)
            
            # --- NEW: Save the annotated frame to disk ---
            annotated_frame = results[0].plot()
            out_writer.write(annotated_frame)
            
            if show_video:
                cv2.imshow(f"Camera: {camera_id}", annotated_frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
    except Exception as e:
        logger.error(f"Fatal error in pipeline: {str(e)}")
    finally:
        logger.info("Shutting down edge node. Flushing remaining telemetry...")
        if cap:
            cap.release()
        if out_writer:
            out_writer.release()  # Close the video writer
            
        # cv2.destroyAllWindows() # <-- Commented out for headless Docker execution
        
        if broker:
            broker.shutdown()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purplle Edge CV Pipeline")
    parser.add_argument("--source", type=str, required=True)
    parser.add_argument("--store", type=str, required=True)
    parser.add_argument("--camera", type=str, required=True)
    parser.add_argument("--api-url", type=str, default="http://localhost:8000/api/v1/events/ingest")
    parser.add_argument("--layout", type=str, default="store_layout.json")
    
    # Swapped default to Nano model to avoid memory limits
    parser.add_argument("--weights", type=str, default="yolov8n.pt") 
    parser.add_argument("--show", action="store_true")
    
    args = parser.parse_args()
    
    run_pipeline(
        source=args.source, 
        store_id=args.store, 
        camera_id=args.camera,
        api_url=args.api_url, 
        layout_path=args.layout, 
        model_weights=args.weights, 
        show_video=args.show
    )