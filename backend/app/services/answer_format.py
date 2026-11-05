"""Remove a whole JSON fence only when requested and validated; no extra inference."""
import json
import re


def requested_json(text):
    head = (text or '').strip()[:500]
    if re.match(r'(?i)^(?:переведи|перефразируй|translate|paraphrase)\b', head):
        return False
    return bool(re.search(r'(?i)\b(?:верни|ответь|выведи|return|respond|output)\b[^\n]{0,100}\bjson\b', head)
                or re.search(r'(?i)(?:^|[.!?\n]\s*)(?:только|only)\s+json\b', head))


def normalize_answer_format(answer, task):
    if not requested_json(task):
        return answer
    match = re.fullmatch(r'\s*```(?:json)?\s*\n?([\s\S]*?)\n?```\s*', answer or '', re.I)
    candidate = match.group(1).strip() if match else (answer or '').strip()
    try:
        json.loads(candidate, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError):
        return answer
    return candidate
