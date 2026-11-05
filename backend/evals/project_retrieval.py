"""Real embedding comparison against the unchanged product search in an isolated DB."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time


def normalize(vector):
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    # Do not consult or mutate the deployed database.
    os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + (target / 'fixture.sqlite').as_posix()
    sys.path.insert(0, '/app')
    sys.path.insert(0, '/app/app/bot_core')
    from config import OPENROUTER_API_KEY
    import httpx
    from app.db.base import Base
    import app.db.models
    from app.db.project_models import Project, ProjectEntry
    from app.db.engine import sync_engine, SyncSessionLocal
    from app.services import project_memory as memory
    fixture = json.loads(Path(__file__).with_name('cases').joinpath('project_retrieval.json').read_text())
    Base.metadata.create_all(sync_engine)
    with SyncSessionLocal() as session:
        session.add(Project(id='eval', user_id=123, name='Synthetic evaluation', created_at=1))
        session.flush()
        for key, title, body, *_ in fixture['records']:
            row = ProjectEntry(id=key, project_id='eval', title=title, body=body, kind='file', source_url='', updated_at=1)
            session.add(row)
            session.flush()
            memory._index(session, row)
        session.commit()
    cases = []
    for key, _, _, dev, held in fixture['records']:
        for split, question in [('development', dev), ('held_out', held)]:
            cases.append({'query':question.removeprefix('exact:'), 'expected':key, 'split':split, 'exact':question.startswith('exact:')})
    cases += [{'query':q, 'expected':None, 'split':'absent', 'exact':False} for q in fixture['absent']]
    documents = [title + '\n' + body for _, title, body, *_ in fixture['records']]
    queries = ['Instruct: Given a question, retrieve relevant passages that answer the question\nQuery: ' + c['query'] for c in cases]
    usage = []
    request_seconds = []
    def embed(texts):
        start = time.monotonic()
        response = httpx.post('https://openrouter.ai/api/v1/embeddings', headers={'Authorization':'Bearer '+OPENROUTER_API_KEY}, json={'model':'qwen/qwen3-embedding-8b', 'input':texts, 'dimensions':1024, 'encoding_format':'float'}, timeout=30)
        request_seconds.append(time.monotonic()-start)
        response.raise_for_status()
        data = response.json()
        usage.append(data.get('usage', {}))
        rows = sorted(data['data'], key=lambda x:x['index'])
        assert len(rows) == len(texts)
        return [normalize(r['embedding']) for r in rows]
    all_vectors = []
    for offset in range(0, len(documents+queries), 24):
        all_vectors.extend(embed((documents+queries)[offset:offset+24]))
    vectors = all_vectors[:len(documents)]
    qvectors = all_vectors[len(documents):]
    # Frozen before evaluating held-out results. Identifier matches retain priority.
    threshold = .55
    import re
    results = []
    for case, query_vector in zip(cases, qvectors):
        lexical = [r['id'] for r in memory.search(123, 'eval', case['query'], 50)]
        similarities = [sum(a*b for a,b in zip(v,query_vector)) for v in vectors]
        semantic = [fixture['records'][i][0] for i in sorted(range(len(vectors)), key=lambda i:-similarities[i]) if similarities[i] >= threshold]
        scores = {}
        for ranking in (lexical, semantic):
            for rank, key in enumerate(ranking):
                scores[key] = scores.get(key,0) + 1/(20+rank+1)
        identifiers = re.findall(r'\b(?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9-]{2,}\b', case['query'])
        pins = [r[0] for r in fixture['records'] if identifiers and all(token.casefold() in (r[1]+'\n'+r[2]).casefold() for token in identifiers)]
        fused = pins + [key for key in sorted(scores,key=lambda key:-scores[key]) if key not in pins]
        results.append({**case, 'lexical':lexical[:5], 'semantic':semantic[:5], 'hybrid':fused[:5], 'max_cosine':max(similarities), 'expected_cosine':similarities[next(i for i,r in enumerate(fixture['records']) if r[0]==case['expected'])] if case['expected'] else None})
    latency = []
    for query in queries[-12:]:
        start = time.monotonic()
        embed([query])
        latency.append(time.monotonic()-start)
    summary = {}
    for split in ('development','held_out'):
        subset=[r for r in results if r['split']==split]
        summary[split] = {name:{'recall_at_1':sum(r['expected'] in r[name][:1] for r in subset)/len(subset), 'recall_at_5':sum(r['expected'] in r[name][:5] for r in subset)/len(subset)} for name in ('lexical','semantic','hybrid')}
    exact=[r for r in results if r['exact']]
    absent=[r for r in results if r['split']=='absent']
    summary['exact_recall_at_1']={name:sum(r['expected'] in r[name][:1] for r in exact)/len(exact) for name in ('lexical','hybrid')}
    summary['absent_nonempty']={name:sum(bool(r[name]) for r in absent) for name in ('lexical','hybrid')}
    summary['cost_usd']=sum(u.get('cost',0) for u in usage)
    summary['prompt_tokens']=sum(u.get('prompt_tokens',0) for u in usage)
    summary['warm_query_p95_seconds']=sorted(latency)[math.ceil(.95*len(latency))-1]
    summary['warm_query_median_seconds']=statistics.median(latency)
    summary['accepted']=(summary['held_out']['hybrid']['recall_at_5']-summary['held_out']['lexical']['recall_at_5'] >= .15 and summary['exact_recall_at_1']['hybrid'] >= summary['exact_recall_at_1']['lexical'] and summary['absent_nonempty']['hybrid'] <= summary['absent_nonempty']['lexical'] and summary['warm_query_p95_seconds'] <= 2 and summary['cost_usd'] <= .01)
    payload={'summary':summary,'threshold':threshold,'results':results,'usage':usage,'latency':latency,'fixture_sha256':hashlib.sha256(Path(__file__).with_name('cases').joinpath('project_retrieval.json').read_bytes()).hexdigest()}
    (target/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    (target/'vectors.json').write_text(json.dumps({'documents':documents,'queries':queries,'vectors':all_vectors}))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
