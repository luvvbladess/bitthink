"""Resolve a project citation to the exact saved revision and bounded passage."""
import re
from app.services import project_memory as memory, project_assets


def read(uid, pid, eid, revision, offset=0):
    item = memory.detail(uid, pid, eid, revision)
    text = item['body']
    offset = max(0, min(int(offset), len(text)))
    excerpt = text[offset:offset + 1400]
    page = None
    # These markers are written by our PDF extractor, not invented by the model.
    markers = [match for match in re.finditer(r'^--- Страница (\d+) ---\s*$', text, re.M) if match.start() <= offset]
    if markers:page = int(markers[-1].group(1))
    original = False
    if revision == item['current_revision']:
        try:
            path, name = project_assets.original(uid, pid, eid)
            original = path.suffix.lower() == '.pdf'
        except ValueError:pass
    return {'entry_id': eid, 'title': item['title'], 'revision': item['revision'], 'offset': offset,
        'excerpt': excerpt, 'page': page, 'pdf_available': original,
        'original_url': f'/projects/{pid}/entries/{eid}/original?revision={revision}' if original else None}
