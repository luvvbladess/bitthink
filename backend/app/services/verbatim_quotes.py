"""Restore a supplied literal only when the answer already matches its text.

No semantic rewriting, quote selection by guesswork or additional model call.
"""
import re


def restore_verbatim_quote(answer, task, messages=()):
    if not re.search(r'(?i)\bдослов\w*', task or '') or re.search(r'(?i)\bне\s+\w*\s*дослов', task or ''):
        return answer
    def quotes(text):
        return re.findall(r'«([^»]*)»', text or '')
    literals = quotes(task)
    if not literals:
        for role in ['user', 'assistant']:
            for row in reversed(messages or []):
                text = row.get('content')
                if row.get('role') == role and isinstance(text, str) and text.strip() != (task or '').strip():
                    literals = quotes(text)
                    if literals:
                        break
            if literals:
                break
    raw = (answer or '').strip()
    if re.search(r'(?i)\bтолько\b|ничего\s+не\s+добавляй', task or ''):
        # A short label is unwanted output when the requested deliverable is
        # only the known literal. Never remove a substantive trailing analysis.
        labeled = re.fullmatch(r'[^«»\n]{1,120}:\s*(«[^»]*»[.!?]?)', raw)
        if labeled:
            raw = labeled[1]
    # Only a complete standalone literal is eligible; never discard analysis.
    match = re.fullmatch(r'«([^»]*)»([.!?]?)', raw)
    body, suffix = (match[1], match[2]) if match else (raw, '')
    normalize = lambda value: value.replace('—', '–')
    matches = list(dict.fromkeys(q for q in literals if normalize(q) == normalize(body)))
    if not matches and match is None and body.endswith(('.', '!', '?')):
        suffix = body[-1]
        matches = list(dict.fromkeys(q for q in literals if normalize(q) == normalize(body[:-1])))
    if len(matches) != 1:
        return answer
    if re.search(r'(?i)\bбез\s+точки\b', task or '') and suffix == '.':
        suffix = ''
    return '«' + matches[0] + '»' + suffix
