"""Presentation transforms must never rewrite code or structured output."""
import json
import re
import uuid


def transform_prose(text, transform):
    if not text:
        return text
    if text.lstrip().startswith(('{', '[')):
        try:
            if isinstance(json.loads(text), (dict, list)):
                return text
        except ValueError:
            pass
    protected = {}
    prefix = '\ue000' + uuid.uuid4().hex + ':'
    def save(value):
        key = prefix + str(len(protected)) + '\ue001'
        protected[key] = value
        return key
    pieces, block = [], []
    fence = None
    for line in text.splitlines(keepends=True):
        if fence is None:
            match = re.match(r'^[ \t]*(`{3,}|~{3,})', line)
            if match:
                fence = match[1]
                block = [line]
            else:
                pieces.append(re.sub(r'(`+)([^\n]*?)\1', lambda m: save(m[0]), line))
        else:
            block.append(line)
            if re.fullmatch(r'[ \t]*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}[ \t]*(?:\r?\n)?', line):
                pieces.append(save(''.join(block)) + ('\n' if line.endswith('\n') else ''))
                block, fence = [], None
    if block:
        pieces.append(save(''.join(block)))  # An unfinished fence still contains code.
    result = transform(''.join(pieces))
    if any(key not in result for key in protected):
        return text  # A prose block deletion must not silently delete executable content.
    for key, value in protected.items():
        # The placeholder's newline preserves prose boundaries during cleanup;
        # the protected value already carries its own trailing newline.
        result = result.replace(key + '\n', value) if value.endswith('\n') else result
        result = result.replace(key, value)
    return result
