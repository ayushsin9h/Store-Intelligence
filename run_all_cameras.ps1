# run_all_cameras.ps1

$cameras = @(
    # --- Bengaluru Flagship (STORE_BLR_001) ---
    # As per your folder structure, these videos are in "Store 2"
    @{ file="data/Store 2/entry 1.mp4"; store="STORE_BLR_001"; cam="CAM_ENTRY_01" },
    @{ file="data/Store 2/entry 2.mp4"; store="STORE_BLR_001"; cam="CAM_ENTRY_02" },
    @{ file="data/Store 2/zone.mp4"; store="STORE_BLR_001"; cam="CAM_SKINCARE_01" },
    @{ file="data/Store 2/billing_area.mp4"; store="STORE_BLR_001"; cam="CAM_CHECKOUT_01" },
    
    # --- Koramangala Express (STORE_BLR_002) ---
    # As per your folder structure, these "CAM" videos are in "Store 1"
    @{ file="data/Store 1/CAM 1 - zone.mp4"; store="STORE_BLR_002"; cam="CAM_ZONE_01" },
    @{ file="data/Store 1/CAM 3 - entry.mp4"; store="STORE_BLR_002"; cam="CAM_ENTRY_01" },
    @{ file="data/Store 1/CAM 2 - zone.mp4"; store="STORE_BLR_002"; cam="CAM_ZONE_02" },
    @{ file="data/Store 1/CAM 5 - billing.mp4"; store="STORE_BLR_002"; cam="CAM_CHECKOUT_01" }
)

Write-Host "🛍️ Starting Purplle Edge Nodes (Sequential Offline Processing)..." -ForegroundColor Magenta

foreach ($c in $cameras) {
    Write-Host "`n[PROCESSING] Store: $($c.store) | Camera: $($c.cam) | File: $($c.file)" -ForegroundColor Cyan
    
    # Running sequentially to prevent RAM starvation and frame-drops
    docker run --rm `
      -v ${PWD}:/app -w /app `
      ultralytics/ultralytics:latest-cpu `
      python -m pipeline.detect `
      --source "$($c.file)" `
      --store $($c.store) `
      --camera $($c.cam) `
      --weights "yolov8n.pt" `
      --api-url http://host.docker.internal:8000/api/v1/events/ingest
      
    Write-Host "[FINISHED] $($c.cam) processed." -ForegroundColor Green
}

Write-Host "`n✅ All 8 cameras processed sequentially. You can now push your /data folder and deploy!" -ForegroundColor Yellow