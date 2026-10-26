"""Anonymous hourly histograms; no prompts, account identifiers or URLs."""
import time
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.db.engine import SyncSessionLocal
from app.db.experience_models import ExperienceMetric

NAMES = {'interaction', 'conversation_open', 'list_load', 'history_load', 'first_token', 'reconnect', 'disconnect', 'queue_wait'}


def record(name, value, device):
    if name not in NAMES or device not in ('mobile', 'desktop', 'server'):return
    value = min(600000, max(0, int(value)))
    bucket = int(time.time()) // 3600 * 3600
    key = f'{bucket}:{device}:{name}'
    values = dict(count=1, total=value, fast=int(value <= 200), medium=int(200 < value <= 1000), slow=int(value > 1000))
    # Update first avoids a read-modify-write race between API processes.
    for attempt in range(3):
        try:
            with SyncSessionLocal.begin() as session:
                result = session.execute(update(ExperienceMetric).where(ExperienceMetric.id == key).values(**{k: getattr(ExperienceMetric, k) + v for k, v in values.items()}))
                if not result.rowcount:session.add(ExperienceMetric(id=key, name=name, device=device, bucket=bucket, **values))
            return
        except IntegrityError:
            if attempt == 2:raise


def summary():
    with SyncSessionLocal() as session:
        rows = session.scalars(select(ExperienceMetric).where(ExperienceMetric.bucket >= int(time.time()) - 7 * 86400)).all()
        groups = {}
        for row in rows:
            group = groups.setdefault((row.name, row.device), dict(name=row.name, device=row.device, count=0, total=0, fast=0, medium=0, slow=0))
            for name in ('count', 'total', 'fast', 'medium', 'slow'):group[name] += getattr(row, name)
        return [{**item, 'average_ms': round(item['total'] / item['count'])} for item in groups.values()]
