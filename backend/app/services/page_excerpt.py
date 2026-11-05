"""Select complementary source spans without a model call or invented content."""
import math
import re
from urllib.parse import unquote, urlsplit

_STOP = {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'what', 'when',
         'documentation', 'docs', 'python', 'asyncio', 'документация', 'сравни',
         'объясни', 'почему', 'когда', 'какой', 'какая', 'между', 'разница'}


def page_excerpt(text, query='', url='', budget=8000):
    """Preserve offsets; repeated boilerplate cannot outweigh coverage."""
    text = text or ''
    if len(text) <= budget:
        return text
    if budget < 200:
        return text[:max(0, budget)]
    query = re.sub(r'https?://\S+', ' ', query or '')
    anchor = unquote(urlsplit(url).fragment)
    words = list(dict.fromkeys(re.findall(r'[\w]+(?:[.]\w+)*', (query + ' ' + anchor).casefold())))
    terms = [w for w in words if len(w) >= 3 and w not in _STOP][:32]
    symbols = list(dict.fromkeys(w.rsplit('.', 1)[-1] for w in terms if '_' in w or '.' in w))[:4]
    terms = list(dict.fromkeys(terms + [part for word in terms for part in word.split('_')
                                      if len(part) >= 4 and part not in _STOP]))[:64]
    def definition(symbol):
        # HTML API signatures often render as module. / name / arguments on
        # separate lines. A linked mention in navigation is not a definition.
        return r'(?m)^[a-z_][\w.]*\.[ \t]*\n[ \t]*' + re.escape(symbol) + r'[ \t]*\n'
    lower = text.casefold()
    definitions = {symbol: list(re.finditer(definition(symbol), lower))[:40] for symbol in symbols}
    defined = sum(bool(matches) for matches in definitions.values())
    width = min(3200, max(1000, (budget - 300) // max(1, min(defined or len(symbols), 3))))
    windows = [(start, min(len(text), start + width)) for start in range(0, len(text), max(600, width - 250))]
    for symbol in symbols:
        for m in definitions[symbol]:
            start = max(0, m.start() - 80)
            windows.append((start, min(len(text), start + width)))
        for m in list(re.finditer(r'(?<!\w)' + re.escape(symbol) + r'(?!\w)', lower))[:160]:
            start = max(0, m.start() - 180)
            windows.append((start, min(len(text), start + width)))
    windows = list(dict.fromkeys(windows))
    bodies = [text[a:b].casefold() for a, b in windows]
    weights = {term: 1 + math.log((len(bodies) + 1) / (1 + sum(term in b for b in bodies))) for term in terms}

    def score(index, focus=None):
        body = bodies[index]
        coverage = sum(weights[t] * min(body.count(t), 2) for t in terms)
        if focus:
            signature = bool(re.search(r'(?<!\w)' + re.escape(focus) + r'\s*\(', body))
            coverage += 30 * signature + 8 * bool(re.search(r'(?<!\w)' + re.escape(focus) + r'(?!\w)', body))
            coverage += 90 * bool(re.search(definition(focus), body))
        return coverage, -windows[index][0]

    chosen = []
    for symbol in symbols:
        if definitions[symbol]:
            # Start at the definition, not a window whose last line happens
            # to mention it. The following conditions must fit in the excerpt.
            start = max(0, definitions[symbol][0].start() - 80)
            chosen.append(windows.index((start, min(len(text), start + width))))
            continue
        candidates = [i for i, body in enumerate(bodies) if symbol in body]
        if candidates:
            chosen.append(max(candidates, key=lambda i: score(i, symbol)))
    ranked = sorted(range(len(windows)), key=score, reverse=True) if terms else list(range(len(windows)))
    spans = []
    used = 0
    for i in list(dict.fromkeys(chosen + ranked)):
        start, end = windows[i]
        if any(max(0, min(end, b) - max(start, a)) > .5 * (end-start) for a, b in spans):
            continue
        room = budget - used - 65
        if room < 200:
            break
        end = min(end, start + room)
        spans.append((start, end))
        used += end-start + 65
    return '\n\n'.join(f'[Фрагмент {a+1}–{b} из {len(text)}]\n{text[a:b]}' for a,b in sorted(spans))[:budget]
