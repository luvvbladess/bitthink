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
        # Drop a filler-only introduction, leaving the code and explanation intact.
        lead = re.match(r'(?i)^\s*конечно,?\s+вот\s+(?:простой\s+)?вариант\s*:\s*(?=```)', answer or '')
        if lead:
            from app.services.response_policy import inline_code_task
            if inline_code_task(task):
                return answer[lead.end():]
        return answer
    match = re.fullmatch(r'\s*```(?:json)?\s*\n?([\s\S]*?)\n?```\s*', answer or '', re.I)
    candidate = match.group(1).strip() if match else (answer or '').strip()
    try:
        json.loads(candidate, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError):
        return answer
    return candidate


def cpp_delimiter_error(task, answer):
    """Return None when a structural check is inapplicable."""
    from app.services.response_policy import inline_code_task

    if not re.search(r'(?i)(?<!\w)[cс]\+\+', task) or not inline_code_task(task):
        return None
    block = re.fullmatch(r'\s*```(?:cpp|c\+\+|cxx)[ \t]*\n([\s\S]*?)\n```\s*', answer, re.I)
    if not block:
        return None
    code = block[1]
    # shortcut: ordinary snippets only; raw strings and preprocessor branches need a compiler.
    if re.search(r'R"|\\\r?\n|(?m:^\s*#\s*(?!include\b|pragma\b)\w+)', code):
        return None
    plain = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:(?:\\.)|[^\'\\\n])*\'', '', code)
    stack = []
    matching = {')': '(', ']': '[', '}': '{'}
    for char in plain:
        if char in '([{':
            stack.append(char)
        elif char in matching and (not stack or stack.pop() != matching[char]):
            return True
    return bool(stack)
