from evals.pure_data_examples import audit_python_examples, python_example_checks


def test_actual_nested_mutation_distinguishes_shallow_and_deep_copy():
    correct = '''```python
import copy
original = [[1, 2]]
shallow = copy.copy(original)
deep = copy.deepcopy(original)
shallow[0].append(3)
print(original)  # [[1, 2, 3]]
print(deep)  # [[1, 2]]
```'''
    assert audit_python_examples(correct) == []
    assert python_example_checks(correct)['checked'] == 2
    broken = correct.replace('shallow[0].append(3)', 'shallow.append(3)')
    issues = audit_python_examples(broken)
    assert len(issues) == 1
    assert issues[0]['actual'] == '[[1, 2]]'


def test_aliasing_without_copy_and_snapshot_at_print_time():
    text = '''```python
a = [1]
b = a
b.append(2)
print(a)  # [1]
b.append(3)
```'''
    issues = audit_python_examples(text)
    assert issues[0]['actual'] == '[1, 2]'


def test_russian_identifiers_and_explanations_after_expected_output():
    text = '''```python
import copy
исходный = [[1], [2]]
поверхностная = copy.copy(исходный)
поверхностная[0].append(9)
print(исходный)  # [[1, 9], [2]] — общий вложенный список
```'''
    assert python_example_checks(text) == {'issues': [], 'checked': 1}


def test_arbitrary_generated_programs_are_not_executed(tmp_path):
    target = tmp_path / 'must-not-exist'
    samples = [f'import os\nopen({str(target)!r}, "w").write("x")\nprint(1) # 2',
               'a = [0] * 1000000000\nprint(a) # []',
               'import copy\nprint(copy.copy.__globals__) # {}',
               'while True: pass\nprint(1) # 2',
               'print = copy.deepcopy\nprint([1]) # [2]']
    for code in samples:
        assert audit_python_examples('```python\n'+code+'\n```') == []
    assert not target.exists()
