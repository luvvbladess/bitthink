"""Bounded checks of pure-data examples; never execute general generated Python."""
import ast
import copy
import json
import math
import re

_NODES = {ast.Module, ast.Import, ast.alias, ast.Assign, ast.Name, ast.Load, ast.Store,
          ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Constant, ast.Expr, ast.Call,
          ast.Attribute, ast.Subscript, ast.Slice, ast.UnaryOp, ast.USub, ast.UAdd}


def _check_example(code):
    if len(code) > 4000:
        return None
    try:
        tree = ast.parse(code)
        nodes = list(ast.walk(tree))
    except (SyntaxError, ValueError, RecursionError):
        return None
    if len(nodes) > 128 or any(type(n) not in _NODES for n in nodes):
        return None
    if sum(isinstance(n, ast.Call) for n in nodes) > 8:
        return None
    imports = [n for n in tree.body if isinstance(n, ast.Import)]
    if any(a.name != 'copy' for n in imports for a in n.names):
        return None
    aliases = {a.asname or a.name for n in imports for a in n.names}
    protected = aliases | {'print', '_capture'}
    for node in nodes:
        if isinstance(node, ast.Name) and (node.id.startswith('__') or
                (isinstance(node.ctx, ast.Store) and node.id in protected)):
            return None
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, str) and len(value) > 2000:
                return None
            if isinstance(value, int) and value.bit_length() > 32:
                return None
            if isinstance(value, float) and not math.isfinite(value):
                return None
        if isinstance(node, ast.Attribute):
            if (node.attr not in {'copy', 'deepcopy', 'append'} or
                    not isinstance(node.value, (ast.Name, ast.Subscript))):
                return None
        if isinstance(node, ast.Call):
            target = node.func
            allowed = (isinstance(target, ast.Name) and target.id == 'print'
                       and len(node.args) == 1 and not node.keywords)
            if isinstance(target, ast.Attribute) and isinstance(target.value, (ast.Name, ast.Subscript)):
                module = isinstance(target.value, ast.Name) and target.value.id in aliases
                allowed = (not node.keywords and len(node.args) == 1 and (
                    target.attr == 'append' and not module or
                    module and target.attr in {'copy', 'deepcopy'}))
            if not allowed:
                return None
    expected = {}
    lines = code.splitlines()
    for node in nodes:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
            # AST columns are UTF-8 byte offsets, including for Russian names.
            tail = lines[node.end_lineno - 1].encode('utf-8')[node.end_col_offset:].decode('utf-8')
            comment = tail.partition('#')[2].strip()
            try:
                # Only a complete literal is an asserted output; prose is not.
                expected[node.lineno] = ast.literal_eval(comment)
            except (ValueError, SyntaxError, RecursionError):
                try:
                    value, end = json.JSONDecoder().raw_decode(comment)
                    if comment[end:].strip().startswith(('—', '–', '-')):
                        expected[node.lineno] = value
                except ValueError:
                    pass
            node.func.id = '_capture'
            node.args.insert(0, ast.Constant(node.lineno))
    if not expected:
        return None
    actual = {}
    def capture(line, value):
        actual[line] = copy.deepcopy(value)
    tree.body = [n for n in tree.body if not isinstance(n, ast.Import)]
    namespace = {'__builtins__': {}, '_capture': capture, **{name: copy for name in aliases}}
    try:
        # No loops, comprehensions, functions, general imports, arbitrary calls,
        # arithmetic, dunder access or I/O survive the checks above. Objects and
        # calls are bounded before execution. This is deliberately a tiny subset.
        exec(compile(ast.fix_missing_locations(tree), '<pure-data-example>', 'exec'), namespace)
        issues = [{'line': line, 'expected': repr(value)[:500], 'actual': repr(actual[line])[:500]}
                  for line, value in expected.items() if line in actual and actual[line] != value]
        return {'issues': issues, 'checked': len(actual)}
    except (Exception, RecursionError):
        return None  # Unsupported demonstration; do not claim it was verified.


def python_example_checks(answer):
    issues, checked = [], 0
    for index, block in enumerate(re.findall(r'```python\s*\n([\s\S]*?)```', answer or '', re.I)):
        result = _check_example(block)
        if result is None:
            continue
        checked += result['checked']
        for issue in result['issues']:
            issues.append({'block': index + 1, **issue})
    return {'issues': issues, 'checked': checked}


def audit_python_examples(answer):
    return python_example_checks(answer)['issues']
