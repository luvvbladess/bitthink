"""python -m evals.quality --report /tmp/quality.json

Offline gate: no network, no model calls, no customer data. Live answers may be
scored with score_answer; its explicit assertions are a regression rubric, not
a universal semantic truth detector.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/bot_core'))
from app.services.request_intent import classify_request


def score_answer(case, answer, sources, *, seconds=0, usage=None):
    from app.services.source_quality import evidence_issues, cited_urls
    evidence = evidence_issues(answer, sources)
    reliability = [error for error in evidence
                   if error not in {'empty_or_failed', 'incomplete_answer_needs_recovery'}]
    completion = [error for error in evidence
                  if error in {'empty_or_failed', 'incomplete_answer_needs_recovery'}]
    errors = list(evidence)
    rubric = case.get('answer', {})
    for pattern in rubric.get('required', []):
        if not re.search(pattern, answer, re.I):
            completion.append('missing_content:' + pattern)
            errors.append(completion[-1])
    for pattern in rubric.get('forbidden', []):
        if re.search(pattern, answer, re.I):
            completion.append('forbidden_content:' + pattern)
            errors.append(completion[-1])
    if len(cited_urls(answer)) < rubric.get('min_citations', 0):
        reliability.append('not_enough_citations')
        errors.append(reliability[-1])
    if sum(s.get('evidence_state') == 'read' for s in sources) < rubric.get('min_read', 0):
        reliability.append('not_enough_read_pages')
        errors.append(reliability[-1])
    if seconds > case.get('max_seconds', 120):
        errors.append('latency_budget')
    # Explicit fixture facts catch wrong values even when the URL is valid.
    # They must only be used with a pinned, dated snapshot, not live prices.
    for fact in rubric.get('facts', []):
        if not re.search(fact, answer, re.I):
            reliability.append('incorrect_snapshot_fact:' + fact)
            completion.append(reliability[-1])
            errors.append(reliability[-1])
    if re.search(r'(?i)\|\s*не подтверждено\s*\||часть цифр или периодов не удалось подтвердить|'
                 r'(?:цен\w*|стоимост\w*)[^.\n]{0,65}(?:не подтвержд\w*|не удалось подтвердить)', answer):
        completion.append('partial_result')
    return dict(id=case['id'], passed=not errors, errors=errors,
                reliability_passed=None if 'empty_or_failed' in evidence else not reliability,
                task_completed=not completion, reliability_errors=reliability, completion_errors=completion,
                seconds=round(seconds, 3), usage=usage,
                citations=len(cited_urls(answer)))


def evaluate_requests(cases):
    from search_engine import query_requires_web
    results=[]
    for case in cases:
        start=time.perf_counter()
        intent=classify_request(case['query'],case.get('history', []))
        web = not intent.web_forbidden and not intent.local and (
            intent.needs_web or query_requires_web(case['query']))
        actual=dict(task=intent.task,web=web,followup=intent.followup,topic=intent.topic)
        errors=[f'{key}: expected {value}, got {actual[key]}'
                for key,value in case['expect'].items() if actual[key] != value]
        results.append(dict(id=case['id'],passed=not errors,errors=errors,
                            seconds=round(time.perf_counter()-start,6),actual=actual))
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    cases=json.loads((ROOT/'evals/cases/requests.json').read_text(encoding='utf-8'))
    if len(cases)<100 or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Need at least 100 uniquely identified cases')
    results=evaluate_requests(cases)
    snapshots=json.loads((ROOT/'evals/cases/evidence.json').read_text(encoding='utf-8'))
    for case in snapshots:
        text=case['text']
        if case.get('clean_first'):
            from kimi_client import strip_source_links
            text=strip_source_links(text)
        scored=score_answer(case,text,case['sources'])
        expected=case['expected_errors']
        errors=[e for e in expected if e not in scored['errors']]
        errors += ['unexpected:'+e for e in scored['errors'] if e not in expected]
        results.append(dict(id=case['id'],passed=not errors,errors=errors))
    failures=[r for r in results if not r['passed']]
    report=dict(kind='offline',network=False,total=len(results),failed=len(failures),
                passed=len(results)-len(failures),results=results)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Quality gate: {report["passed"]}/{report["total"]} passed')
    for row in failures: print(row['id'], '; '.join(row['errors']))
    return int(bool(failures))


if __name__=='__main__':
    raise SystemExit(main())
