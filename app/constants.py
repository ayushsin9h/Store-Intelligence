# app/constants.py

# ------------------------------------------------------------------
# Event Types
# Single Source of Truth
# ------------------------------------------------------------------

ENTRY = "entry"
EXIT = "exit"
REENTRY = "reentry"

ZONE_ENTERED = "zone_entered"
ZONE_EXITED = "zone_exited"

QUEUE_COMPLETED = "queue_completed"
QUEUE_ABANDONED = "queue_abandoned"

# ------------------------------------------------------------------
# Session Configuration
# ------------------------------------------------------------------

SESSION_TIMEOUT_SECONDS = 5 * 60

# ------------------------------------------------------------------
# Anomaly Types
# ------------------------------------------------------------------

QUEUE_SPIKE = "QUEUE_SPIKE"
CONVERSION_DROP = "CONVERSION_DROP"
DEAD_ZONE = "DEAD_ZONE"
STALE_FEED = "STALE_FEED"

# ------------------------------------------------------------------
# Health Status
# ------------------------------------------------------------------

STATUS_OK = "OK"
STATUS_DEGRADED = "DEGRADED"
STATUS_OFFLINE = "OFFLINE"