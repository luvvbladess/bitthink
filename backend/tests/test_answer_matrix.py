import json
import unittest
from evals.answer_matrix import CASES, MODES, summarize


class AnswerMatrixTest(unittest.TestCase):
    def test_coverage(self):
        cases = json.loads(CASES.read_text(encoding='utf-8'))
        self.assertEqual(len(cases), 90)
        self.assertEqual(len({c['id'] for c in cases}), 90)
        for mode in MODES:
            rows = [c for c in cases if c['mode'] == mode]
            self.assertEqual(len(rows), 15)
            self.assertTrue(any(c['expect']['web'] for c in rows))
            self.assertTrue(all(c['review_criteria'] and c['query'] for c in rows))
            self.assertTrue(all('?' * 5 not in c['query'] for c in rows))

    def test_diagnostics_preserve_incomplete_and_reasons(self):
        report = dict(requested=2, completed=1, results=[dict(mode='auto', topic='math',
            passed=False, errors=['wrong'], judgment={'reasons':['fix calculation']})])
        summary = summarize(report)
        self.assertTrue(summary['incomplete'])
        self.assertEqual(summary['problems'], {'wrong':1})
        self.assertEqual(summary['by_mode_and_topic']['auto/math']['improvements'], ['fix calculation'])
    def test_math_accepts_grouped_digits(self):
        import re
        cases = json.loads(CASES.read_text(encoding='utf-8'))
        pattern = next(c for c in cases if c['topic'] == 'math')['answer']['required'][0]
        for answer in ('7680', '7 680', '7\u202f680'):
            self.assertIsNotNone(re.search(pattern, answer))
        self.assertIsNone(re.search(pattern, '7600'))
