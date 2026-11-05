"""Bounded arithmetic, not Python execution. No I/O, variables or attributes."""
import ast
from decimal import Decimal, localcontext, ROUND_HALF_UP
from fractions import Fraction
import math
import operator

PRECISION = 34
MAX_BITS = 4096


class CalculationError(ValueError):
    pass


def _limit(value):
    if isinstance(value, Fraction):
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS:
            raise CalculationError('Число слишком велико.')
    elif isinstance(value, Decimal):
        if not value.is_finite() or (value and abs(value.adjusted()) > 1000):
            raise CalculationError('Результат вне допустимого диапазона.')
    else:
        raise CalculationError('Ожидалось число.')
    return value


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(value.numerator) / Decimal(value.denominator)


def evaluate(expression):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 1000:
        raise CalculationError('Нужно выражение длиной до 1000 символов.')
    expression = expression.strip()
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        raise CalculationError('Неверная запись выражения.') from None
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise CalculationError('Слишком сложное выражение.')

    def integer(value, maximum):
        if not isinstance(value, Fraction) or value.denominator != 1 or not 0 <= value <= maximum:
            raise CalculationError('Аргумент должен быть целым в допустимом диапазоне.')
        return value.numerator

    def visit(node, depth=0):
        if depth > 20:
            raise CalculationError('Слишком глубокое выражение.')
        child = lambda n: visit(n, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            literal = ast.get_source_segment(expression, node) or ''
            if len(literal) > 128 or re_exponent(literal) > 512:
                raise CalculationError('Слишком большая числовая константа.')
            return _limit(Fraction(literal.replace('_', '')))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return _limit(child(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1))
        if isinstance(node, ast.BinOp):
            left, right = child(node.left), child(node.right)
            if isinstance(node.op, ast.Pow):
                exponent = integer(right if right >= 0 else -right, 64) * (-1 if right < 0 else 1)
                if isinstance(left, Fraction) and max(left.numerator.bit_length(), left.denominator.bit_length()) * abs(exponent) > MAX_BITS:
                    raise CalculationError('Слишком большая степень.')
                return _limit(left ** exponent)
            functions = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                         ast.Div: operator.truediv, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
            operation = functions.get(type(node.op))
            if operation is None:
                raise CalculationError('Операция не поддерживается.')
            if isinstance(left, Decimal) or isinstance(right, Decimal):
                left, right = _decimal(left), _decimal(right)
            value = operation(left, right)
            return _limit(Fraction(value) if isinstance(value, int) else value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            args = [child(a) for a in node.args]
            if name == 'comb' and len(args) == 2:
                n, k = integer(args[0], 5000), integer(args[1], 5000)
                if k > n:
                    raise CalculationError('Для comb требуется 0 ≤ k ≤ n.')
                return _limit(Fraction(math.comb(n, k)))
            if name == 'factorial' and len(args) == 1:
                return _limit(Fraction(math.factorial(integer(args[0], 500))))
            if name == 'abs' and len(args) == 1:
                return _limit(abs(args[0]))
            if name == 'sqrt' and len(args) == 1 and args[0] >= 0:
                value = args[0]
                if isinstance(value, Fraction):
                    a, b = math.isqrt(value.numerator), math.isqrt(value.denominator)
                    if a*a == value.numerator and b*b == value.denominator:
                        return Fraction(a, b)
                return _limit(_decimal(value).sqrt())
            if name == 'round' and len(args) == 2:
                places = integer(args[1], 18)
                return _limit(_decimal(args[0]).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))
            raise CalculationError('Допустимы comb, factorial, sqrt, abs и round(x, digits).')
        raise CalculationError('Допустимы только числа, арифметика и перечисленные функции.')

    try:
        with localcontext() as context:
            context.prec = PRECISION
            value = visit(tree.body)
            result = format(_decimal(value), 'f')
            return {'ok': True, 'expression': expression, 'result': result,
                    'exact_rational': str(value) if isinstance(value, Fraction) else None,
                    'precision_digits': PRECISION, 'rounding': 'ROUND_HALF_UP for round()'}
    except CalculationError:
        raise
    except (ArithmeticError, ValueError, TypeError, RecursionError):
        raise CalculationError('Вычисление невозможно: проверь числа, деление на ноль и область определения.') from None


def re_exponent(literal):
    import re
    match = re.search(r'[eE]([+-]?\d+)$', literal.replace('_', ''))
    return abs(int(match[1])) if match else 0


def calculate(expression):
    try:
        return evaluate(expression)
    except CalculationError as error:
        return {'ok': False, 'error': str(error)}
