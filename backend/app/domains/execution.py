"""Read models and controls shared by chat activity surfaces."""
import json
from sqlalchemy import select, update
from app.db.engine import SyncSessionLocal
from app.db.generation_models import Generation
from app.db.models import Conversation
from app.services.generation_store import ACTIVE


def activity(email):
    with SyncSessionLocal() as session:
        rows = session.execute(select(Generation, Conversation.title).join(Conversation, Conversation.id == Generation.conversation_id).where(Generation.user_email == email, Generation.kind != 'external', Conversation.deleted_at.is_(None)).order_by(Generation.created_at.desc()).limit(50))
        result = []
        for row, title in rows:
            snapshot = json.loads(row.snapshot)
            result.append(dict(id=row.id, conversation_id=row.conversation_id, status=row.status,
                prompt=(snapshot.get('user_text') or title)[:180], progress=snapshot.get('status_text', '') if row.status in ACTIVE else '',
                created_at=row.created_at, error=snapshot.get('error', ''), kind='chat'))
        return result


def stop(email, generation_id):
    with SyncSessionLocal.begin() as session:
        result = session.execute(update(Generation).where(Generation.id == generation_id,
            Generation.user_email == email, Generation.status.in_(ACTIVE)).values(cancel_requested=True))
        return bool(result.rowcount)
