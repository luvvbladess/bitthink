"""Explicit paid integration evaluation, isolated from customer chat history.

python -m evals.live --live --ids q001,q021,q033,q047 --report /tmp/live.json
Uses the internal Creator account and the real Auto pipeline, with normal usage
accounting. Never invoke inside a serving worker: patches are process-local.
"""
import argparse
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import statistics
import time
from types import SimpleNamespace as NS
from unittest.mock import patch

from evals.quality import ROOT, score_answer


async def run(cases, report_path, max_usd, use_judge=False):
    from sqlalchemy import select
    from app.db.engine import SyncSessionLocal
    from app.db.models import Subscription
    from app.billing.costs import model_cost_usd
    from conversations import conversation_manager as manager
    from handlers.core import get_smart_response
    from app.services.run_protocol import RunRecord, current_run
    from app.services.request_intent import classify_request
    with SyncSessionLocal() as session:
        user=session.scalar(select(Subscription.user_id).where(Subscription.tier=='creator').limit(1))
    if not user:
        raise RuntimeError('Internal Creator account required; no customer fallback')
    results=[]
    spent=0.0
    original_track=manager.track_tokens
    for case in cases:
        if spent >= max_usd:
            break
        usage=[]
        def track(uid, model, inp=0, out=0, cached=0, writes=0, **kwargs):
            usage.append(dict(model=model,input_tokens=inp,output_tokens=out,cached_input_tokens=cached,
                              estimated_usd=model_cost_usd(model,inp,out,cached_input_tokens=cached)))
            return original_track(uid,model,inp,out,cached,writes,**kwargs)
        query=case['query']
        history=list(case.get('history', []))
        messages=history+[dict(role='user',content=query)]
        snapshot=NS(messages=[NS(**dict(m,search=None)) for m in messages])
        record=RunRecord(requires_sources=case['expect']['web'])
        token=current_run.set(record)
        started=time.monotonic()
        answer=''
        sources=[]
        exception=''
        try:
            with ExitStack() as stack:
                import app.services.source_quality as source_quality
                original_partial=source_quality.supported_partial
                filtered_drafts=[]
                def trace_partial(draft,rows,**kwargs):
                    filtered_drafts.append(dict(text=draft,issues=source_quality.evidence_issues(draft,rows)))
                    return original_partial(draft,rows,**kwargs)
                stack.enter_context(patch.object(source_quality,'supported_partial',side_effect=trace_partial))
                stack.enter_context(patch.object(manager,'get_user_model',return_value='auto'))
                stack.enter_context(patch.object(manager,'conversation_for_turn',return_value=snapshot))
                stack.enter_context(patch.object(manager,'track_tokens',side_effect=track))
                answer,_,_,sources=await asyncio.wait_for(
                    get_smart_response(user,query,messages,None),case.get('max_seconds',120))
        except asyncio.TimeoutError:
            exception='timeout'
        except Exception as exc:
            exception=type(exc).__name__  # no secrets from provider exception text
        finally:
            current_run.reset(token)
        seconds=time.monotonic()-started
        judgment=None
        grading_started=time.monotonic()
        if use_judge and not exception:
            from evals.judge import judge_answer
            try:
                with patch.object(manager,'track_tokens',side_effect=track):
                    judgment=await asyncio.wait_for(judge_answer(case,answer,sources,record.page_texts,user),50)
            except Exception as exc:
                exception='grader_'+type(exc).__name__
        grading_seconds=time.monotonic()-grading_started
        usd=sum(r['estimated_usd'] for r in usage)
        spent+=usd
        live_case=dict(case)
        rubric=dict(case.get('answer', {}))
        if case['expect']['web']:
            rubric.setdefault('min_citations',1)
            rubric.setdefault('min_read',1)
        rubric.setdefault('forbidden',[r'^\s*(?:извини|прошу прощения)',r'пришли.{0,40}скриншот тарифа'])
        live_case['answer']=rubric
        scored=score_answer(live_case,answer,sources,seconds=seconds,usage=usage)
        if exception:
            scored['errors'].append(exception)
        if judgment and judgment['usefulness']=='failed':
            scored['errors'].append('grader_unhelpful')
        if judgment and case['expect']['web'] and judgment['grounding']!='supported':
            scored['errors'].append('grader_grounding_'+judgment['grounding'])
        intent=classify_request(query,history)
        if intent.web_forbidden and record.sources:
            scored['errors'].append('web_despite_optout')
        scored.update(passed=not scored['errors'],query=query,answer=answer,
                      estimated_usd=round(usd,6),human_semantic_review_required=True,
                      judgment=judgment,grading_seconds=round(grading_seconds,2),
                      filtered_drafts=filtered_drafts,
                      sources=sources,tools=record.tools)
        results.append(scored)
        report=dict(kind='live',requested=len(cases),completed=len(results),
                    failed=sum(not r['passed'] for r in results),
                    estimated_usd=round(spent,6),cost_basis='configured list prices, excludes external tool fees',
                    median_seconds=round(statistics.median(r['seconds'] for r in results),2),
                    results=results)
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
        print(json.dumps(dict(id=case['id'],passed=scored['passed'],errors=scored['errors'],
                              seconds=round(seconds,1),estimated_usd=round(usd,5)),ensure_ascii=False),flush=True)
    return int(len(results)!=len(cases) or any(not r['passed'] for r in results))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',required=True,help='Explicitly enable paid model calls')
    parser.add_argument('--ids',required=True,help='Comma-separated fixture IDs; explicit selection avoids surprise full-suite spend')
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--max-usd',default=1.0,type=float,help='Stop starting cases after this estimated spend; not a hard per-call provider cap')
    parser.add_argument('--judge',action='store_true',help='Also run a metered evidence-based model grader')
    args=parser.parse_args()
    if not 0 < args.max_usd <= 20:
        parser.error('max-usd must be >0 and <=20')
    all_cases=json.loads((ROOT/'evals/cases/requests.json').read_text(encoding='utf-8'))
    ids=list(dict.fromkeys(args.ids.split(',')))
    cases=[next((c for c in all_cases if c['id']==i),None) for i in ids]
    if any(c is None for c in cases):
        parser.error('Unknown fixture ID')
    raise SystemExit(asyncio.run(run(cases,args.report,args.max_usd,args.judge)))


if __name__=='__main__':
    main()
