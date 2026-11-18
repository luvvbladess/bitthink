"""Cross-mode answer diagnostics. Run from backend; see evals/ANSWER_MATRIX.md."""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path

CASES = Path(__file__).parent / 'cases/answer_matrix.json'
MODES = ('auto', 'gpt-6-sol', 'director', 'docgen')


def summarize(report):
    groups = {}
    for row in report.get('results', []):
        key = row['mode'] + '/' + row['topic']
        groups[key] = dict(passed=row['passed'], errors=row['errors'],
                           verification_required=row.get('verification_required', False),
                           improvements=(row.get('judgment') or {}).get('reasons', []),
                           review_criteria=row.get('review_criteria', []))
    return dict(requested=report['requested'], completed=report['completed'],
                incomplete=report['completed'] != report['requested'],
                problems=dict(Counter(e for r in report['results'] for e in r['errors'])),
                by_mode_and_topic=groups,
                note='Automated checks and model judgments require human review; unknown grounding is not proven falsehood.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--modes', default=','.join(MODES))
    parser.add_argument('--topics', help='Comma-separated topics; omitted means all')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--max-usd', type=float, default=1)
    args = parser.parse_args()
    modes = args.modes.split(',')
    cases = json.loads(CASES.read_text(encoding='utf-8'))
    topics = args.topics.split(',') if args.topics else sorted({c['topic'] for c in cases})
    if set(modes) - set(MODES) or set(topics) - {c['topic'] for c in cases}:
        parser.error('Unknown mode or topic')
    if not 0 < args.max_usd <= 20:
        parser.error('max-usd must be >0 and <=20')
    selected = [c for c in cases if c['mode'] in modes and c['topic'] in topics]
    if not args.live:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(dict(kind='plan_only', cases=selected), ensure_ascii=False, indent=2), encoding='utf-8')
        return
    from evals.live import run
    result = asyncio.run(run(selected, args.report, args.max_usd, use_judge=True))
    report = json.loads(args.report.read_text(encoding='utf-8'))
    args.report.with_suffix('.summary.json').write_text(json.dumps(summarize(report), ensure_ascii=False, indent=2), encoding='utf-8')
    raise SystemExit(result)


if __name__ == '__main__':
    main()
