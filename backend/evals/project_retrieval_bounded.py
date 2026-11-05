"""Exercise the actual hybrid search, real API deadlines, and cached fallback."""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    target=Path(args.output).resolve();target.mkdir(parents=True,exist_ok=True)
    assert not (target/'fixture.sqlite').exists(), 'Use a fresh isolated output directory'
    from dotenv import load_dotenv
    load_dotenv('/app/.env')
    os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(target/'fixture.sqlite').as_posix()
    os.environ['PROJECT_EMBEDDINGS_ENABLED']='true'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from app.db.base import Base
    import app.db.models
    from app.db.engine import sync_engine,SyncSessionLocal
    from app.db.project_models import Project,ProjectEntry
    from app.services import project_memory as memory,project_embeddings as emb
    Base.metadata.create_all(sync_engine)
    cases_dir=Path(__file__).with_name('cases')
    original=json.loads((cases_dir/'project_retrieval.json').read_text())
    fresh=json.loads((cases_dir/'project_retrieval_fresh.json').read_text())
    records=original['records']+fresh['records']
    # Production schedules this work. The eval explicitly waits for the same
    # real indexer, avoiding incidental background races in its isolated DB.
    emb.schedule=lambda *args:None
    uid,pid=123,'bounded-eval'
    with SyncSessionLocal() as session:
        session.add(Project(id=pid,user_id=uid,name='Synthetic test',created_at=1));session.flush()
        for key,title,body,*_ in records:
            row=ProjectEntry(id=key,project_id=pid,title=title,body=body,kind='file',source_url='',updated_at=1)
            session.add(row);session.flush();memory._index(session,row)
        session.commit()
    usage=[]
    actual_client=emb._http_client()
    class MeteredClient:
        def post(self,*args,**kwargs):
            response=actual_client.post(*args,**kwargs)
            if response.is_success:usage.append(response.json().get('usage') or {})
            return response
    emb._http_client=lambda:MeteredClient()
    assert emb.index_project(uid,pid,[r[0] for r in records])==len(records)
    cases=[]
    for index,record in enumerate(records):
        key,_,_,dev,held=record
        for n,question in enumerate((dev,held)):
            cases.append({'query':question.removeprefix('exact:'),'expected':key,
                'group':('regression' if index<len(original['records']) else 'fresh'),
                'exact':question.startswith('exact:'),'split':n})
    cases += [{'query':q,'expected':None,'group':'absent','exact':False,'split':0} for q in original['absent']]
    outcomes=[]
    actual_query=emb.query_vector
    last={'available':False}
    def observed_query(*args):
        value=actual_query(*args);last['available']=value is not None;return value
    emb.query_vector=observed_query
    for case in cases:
        baseline=memory._lexical_search(uid,pid,case['query'],5)
        start=time.monotonic()
        result=memory.search(uid,pid,case['query'],5)
        outcomes.append({**case,'lexical':[r['id'] for r in baseline],
            'hybrid':[r['id'] for r in result],'seconds':time.monotonic()-start,
            'vector_available':last['available']})
    # Cached repeated question should avoid another paid request.
    repeat=cases[-1]['query'];before=len(usage)
    start=time.monotonic();memory.search(uid,pid,repeat,5)
    cached_seconds=time.monotonic()-start
    cache_hit=len(usage)==before
    # Independently inject a transport that ignores HTTP timeout. Product must
    # fall back within its own deadline, not wait for transport completion.
    actual_embed=emb.embed
    def slow_embed(texts,**kwargs):
        time.sleep(2.0)
        return [(1.,)+(0.,)*(emb.DIMENSIONS-1)]
    emb.embed=slow_embed
    slow_question='Проверь недоступный сетевой источник для кварца'
    expected=memory._lexical_search(uid,pid,slow_question,5)
    start=time.monotonic();fallback=memory.search(uid,pid,slow_question,5)
    slow_seconds=time.monotonic()-start
    emb.embed=actual_embed
    summary={}
    for group in ('regression','fresh'):
        subset=[r for r in outcomes if r['group']==group and (group=='fresh' or r['split']==1)]
        summary[group]={'count':len(subset)}
        for name in ('lexical','hybrid'):
            summary[group][name+'_hits_at_5']=sum(r['expected'] in r[name] for r in subset)
            summary[group][name+'_hits_at_1']=sum(r['expected'] in r[name][:1] for r in subset)
    exact=[r for r in outcomes if r['exact']]
    absent=[r for r in outcomes if r['group']=='absent']
    summary['exact']={name:sum(r['expected'] in r[name][:1] for r in exact) for name in ('lexical','hybrid')}
    summary['absent_nonempty']={name:sum(bool(r[name]) for r in absent) for name in ('lexical','hybrid')}
    times=sorted(r['seconds'] for r in outcomes)
    summary.update({'case_count':len(outcomes),'p95_seconds':times[math.ceil(.95*len(times))-1],
        'max_seconds':max(times),'median_seconds':statistics.median(times),
        'vector_available':sum(r['vector_available'] for r in outcomes),
        'cached_seconds':cached_seconds,'cache_hit':cache_hit,'forced_slow_seconds':slow_seconds,
        'forced_slow_matches_lexical':fallback==expected,'cost_usd':sum(u.get('cost',0) for u in usage),
        'api_calls':len(usage),'prompt_tokens':sum(u.get('prompt_tokens',0) for u in usage)})
    old,new=summary['regression'],summary['fresh']
    summary['accepted']=(
        (old['hybrid_hits_at_5']-old['lexical_hits_at_5'])/old['count']>=.15 and
        (new['hybrid_hits_at_5']-new['lexical_hits_at_5'])/new['count']>=.10 and
        summary['exact']['hybrid']>=summary['exact']['lexical'] and
        summary['absent_nonempty']['hybrid']<=summary['absent_nonempty']['lexical'] and
        summary['p95_seconds']<1.3 and summary['max_seconds']<1.6 and
        slow_seconds<1.3 and fallback==expected and cache_hit and summary['cost_usd']<.01)
    (target/'results.json').write_text(json.dumps({'summary':summary,'outcomes':outcomes,'usage':usage},ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
