"""Evaluate saved real answers, plus deterministic Word export and scorer controls.

--fixtures exercises the evaluator and real export, not model intelligence.
--responses accepts isolated live-run results keyed by case ID; no customer data.
"""
import argparse
import io
import json
from pathlib import Path
import re
import time
import zipfile
import xml.etree.ElementTree as ET

CASES = Path(__file__).parent / 'cases/product_journeys.json'


def artifact_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = ET.fromstring(archive.read('word/document.xml'))
        return ' '.join(node.text or '' for node in xml.iter() if node.tag.endswith('}t'))


def score(case, text, seconds=0):
    errors = ['missing:' + pattern for pattern in case.get('required', []) if not re.search(pattern, text, re.I | re.S)]
    errors += ['forbidden:' + pattern for pattern in case.get('forbidden', []) if re.search(pattern, text, re.I | re.S)]
    if seconds > case['max_seconds']:errors.append('latency_budget')
    return dict(id=case['id'], passed=not errors, errors=errors, seconds=round(seconds, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fixtures', action='store_true')
    mode.add_argument('--responses', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(CASES.read_text(encoding='utf-8'))
    responses = json.loads(args.responses.read_text(encoding='utf-8')) if args.responses else {}
    results = []
    for case in cases:
        started = time.monotonic()
        if args.fixtures:
            text = case['reference']
            if case.get('artifact') == 'docx':
                import app.core.legacy  # establish the engine's import boundary
                from docx_generator import convert_markdown_to_docx
                text = artifact_text(convert_markdown_to_docx(text))
            result = score(case, text, time.monotonic() - started)
            # Negative control: a plausible-looking but factually empty answer
            # must not pass simply because the export opens or HTTP was 200.
            if score(case, 'Готово, всё проверено.')['passed']:result.update(passed=False, errors=['negative_control_accepted'])
        else:
            response = responses.get(case['id'])
            if not response:
                result = dict(id=case['id'], passed=False, errors=['missing_live_result'])
            else:result = score(case, response['text'], response.get('seconds', 0))
        results.append(result)
    report = dict(kind='fixtures-and-real-export' if args.fixtures else 'live-responses', total=len(results), passed=sum(row['passed'] for row in results), results=results)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Product journeys ({report["kind"]}): {report["passed"]}/{report["total"]} passed')
    for row in results:
        if not row['passed']:print(row['id'], row['errors'])
    return int(report['passed'] != report['total'])


if __name__ == '__main__':raise SystemExit(main())
