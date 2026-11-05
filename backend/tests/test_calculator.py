from decimal import Decimal
import pytest
from app.services.calculator import calculate


@pytest.mark.parametrize('expression,exact', [
    ('0.1 + 0.2', '3/10'), ('1/17+1/19+1/23', '1151/7429'),
    ('(987654321987654321*123456789123456789)%1000000007', '327846861'),
    ('comb(50,8)', '536878650'), ('factorial(6)', '720'),
    ('sqrt(81/16)', '9/4'), ('2**-3', '1/8'), ('-9 // 2', '-5'),
])
def test_exact_arithmetic(expression, exact):
    result = calculate(expression)
    assert result['ok']
    assert result['exact_rational'] == exact


def test_rounding_after_sum_and_irrational_precision():
    assert calculate('round(0.105+0.105+0.105,2)')['result'] == '0.32'
    root = calculate('sqrt(2)')
    assert root['ok'] and root['exact_rational'] is None
    assert abs(Decimal(root['result']) - Decimal('1.414213562373095048801688724209698')) < Decimal('1e-32')


@pytest.mark.parametrize('expression', [
    '__import__("os").system("whoami")', 'open("file")', '(1).__class__',
    '[x for x in range(100)]', 'True+1', '2**1000000000', '1e-1000000',
    'factorial(100000)', 'comb(5000,6000)', '1/0', 'sqrt(-1)', 'round(2,1000)',
    '[]', 'x+1', '9<<1000000', '"a"*10',
])
def test_unbounded_or_non_arithmetic_input_is_rejected(expression):
    assert calculate(expression)['ok'] is False
