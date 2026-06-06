import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select, and_

from app.storage.database import Session as SessionModel
from app.engines.zones import build_heatmap_density_matrix

logger = logging.getLogger(__name__)

class SimpleTTLCache:
    def __init__(self, default_ttl_seconds: int = 30):
        self._cache = {}
        self.default_ttl = default_ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            entry = self._cache[key]
            if time.time() - entry['timestamp'] < entry['ttl']:
                return entry['data']
            else:
                del self._cache[key]
        return None

    def set(self, key: str, data: Any, ttl_seconds: Optional[int] = None):
        self._cache[key] = {
            'data': data,
            'timestamp': time.time(),
            'ttl': ttl_seconds or self.default_ttl
        }

    def invalidate_store(self, store_id: str):
        keys = [f'metrics_{store_id}', f'funnel_{store_id}', f'heatmap_{store_id}']
        for key in keys:
            self._cache.pop(key, None)

olap_cache = SimpleTTLCache(default_ttl_seconds=15)

def get_cached_metrics(db: DBSession, store_id: str) -> Dict[str, Any]:
    cache_key = f'metrics_{store_id}'
    cached_data = olap_cache.get(cache_key)
    if cached_data: return cached_data
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = db.execute(select(SessionModel).where(and_(SessionModel.store_id == store_id, SessionModel.start_time >= today))).scalars().all()
    total_visitors = len(sessions)
    converted_visitors = sum(1 for s in sessions if s.is_converted)
    conversion_rate = (converted_visitors / total_visitors * 100.0) if total_visitors > 0 else 0.0
    active_queue = sum(1 for s in sessions if s.end_time is None and s.journey_path and s.journey_path.endswith('CHECKOUT'))
    converted_sessions = [s for s in sessions if s.is_converted and s.total_dwell_seconds]
    avg_wait = sum(s.total_dwell_seconds for s in converted_sessions) / len(converted_sessions) if converted_sessions else 0.0
    metrics = {'store_id': store_id, 'total_unique_visitors': total_visitors, 'converted_visitors': converted_visitors, 'real_time_conversion_rate': round(conversion_rate, 2), 'active_queue_depth': active_queue, 'average_wait_time_seconds': round(avg_wait, 1)}
    olap_cache.set(cache_key, metrics)
    return metrics

def get_cached_funnel(db: DBSession, store_id: str) -> Dict[str, Any]:
    cache_key = f'funnel_{store_id}'
    cached_data = olap_cache.get(cache_key)
    if cached_data: return cached_data
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = db.execute(select(SessionModel).where(and_(SessionModel.store_id == store_id, SessionModel.start_time >= today))).scalars().all()
    ingress_count = len(sessions)
    browse_count = intent_count = convert_count = 0
    for sess in sessions:
        tokens = [t.strip() for t in (sess.journey_path or '').split('->') if t.strip()]
        if [t for t in tokens if t not in ('ENTRY', 'EXIT', 'REENTRY')]: browse_count += 1
        if 'CHECKOUT' in tokens or 'QUEUE_DROP' in tokens: intent_count += 1
        if sess.is_converted: convert_count += 1
    def calc_drop(curr: int, prev: int) -> float: return round((curr / prev) * 100.0, 2) if prev > 0 else 0.0
    funnel = {'store_id': store_id, 'window_start': today.isoformat(), 'window_end': datetime.now(timezone.utc).isoformat(), 'funnel_stages': [{'stage_name': 'Ingress', 'visitor_count': ingress_count, 'conversion_percentage': 100.0}, {'stage_name': 'Browse', 'visitor_count': browse_count, 'conversion_percentage': calc_drop(browse_count, ingress_count)}, {'stage_name': 'Intent', 'visitor_count': intent_count, 'conversion_percentage': calc_drop(intent_count, browse_count)}, {'stage_name': 'Convert', 'visitor_count': convert_count, 'conversion_percentage': calc_drop(convert_count, intent_count)}]}
    olap_cache.set(cache_key, funnel)
    return funnel

def get_cached_heatmap(db: DBSession, store_id: str) -> Dict[str, Any]:
    cache_key = f'heatmap_{store_id}'
    cached_data = olap_cache.get(cache_key)
    if cached_data: return cached_data
    data_points = build_heatmap_density_matrix(db, store_id, grid_size=20)
    heatmap = {'store_id': store_id, 'data_confidence': len(data_points) > 0, 'data_points': data_points}
    olap_cache.set(cache_key, heatmap, ttl_seconds=30)
    return heatmap
