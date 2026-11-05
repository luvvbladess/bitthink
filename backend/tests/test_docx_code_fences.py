from io import BytesIO
import pytest
from docx import Document
from docx_generator import convert_markdown_to_docx, scrub_markdown_marks


REPORT = '''# Алгоритм Дейкстры

## 4. Реализация

```cpp
#include <vector>
int main() {
    const char* literal = "** value **";
    return 0;
}
```

## 5. Пример работы

Входные данные:

```text
5 6 1
1 2 4
1 3 1
3 2 2
2 4 1
3 4 5
4 5 3
```

Ожидаемый вывод:

```text
Вершина 1: расстояние = 0, путь: 1
Вершина 2: расстояние = 3, путь: 1 -> 3 -> 2
```

Сначала из вершины `1` находятся расстояния `4` и `1`.

Сборка и запуск исходного кода в `main.cpp`:

```bash
g++ -std=c++17 -O2 -Wall -Wextra -pedantic main.cpp -o dijkstra
./dijkstra < input.txt
```

## 6. Вывод

Веса рёбер неотрицательны.
'''


def test_code_closing_fence_never_consumes_following_report_sections():
    raw=convert_markdown_to_docx(REPORT)
    doc=Document(BytesIO(scrub_markdown_marks(raw)))
    paragraphs=doc.paragraphs
    example=next(p for p in paragraphs if 'Пример работы' in p.text)
    assert example.style.name.startswith('Heading')
    assert example.text=='Пример работы'
    prose='\n'.join(p.text for p in paragraphs if p.style.name!='BT Code')
    assert '```' not in prose and '##' not in prose and '`1`' not in prose
    assert 'Сначала из вершины 1 находятся расстояния 4 и 1.' in prose
    code=[p.text for p in paragraphs if p.style.name=='BT Code']
    assert '#include <vector>' in code
    assert '    const char* literal = "** value **";' in code
    assert code[code.index('5 6 1'):code.index('5 6 1')+7]==['5 6 1','1 2 4','1 3 1','3 2 2','2 4 1','3 4 5','4 5 3']
    assert './dijkstra < input.txt' in code
    assert not any('```' in p.text or p.text=='bash' for p in paragraphs)


@pytest.mark.parametrize('fence',['```','````','~~~','~~~~~'])
def test_fences_match_type_and_length_and_preserve_real_code_symbols(fence):
    literal=['#include <vector>','    ** keep spaces **','1.','*','> a >> b']
    if len(fence)>3:literal+=['```']
    source=fence+'cpp\n'+'\n'.join(literal)+'\n'+fence+fence[0]+'\n\n## После кода\n\nОбычный текст с `x ** 2`.'
    doc=Document(BytesIO(scrub_markdown_marks(convert_markdown_to_docx(source))))
    assert [p.text for p in doc.paragraphs if p.style.name=='BT Code']==literal
    heading=next(p for p in doc.paragraphs if p.text=='После кода')
    assert heading.style.name.startswith('Heading')
    assert any('x ** 2' in p.text for p in doc.paragraphs)
    for paragraph in doc.paragraphs:
        if paragraph.style.name=='BT Code':
            assert paragraph.style.font.name=='Courier New'
            assert paragraph.paragraph_format.first_line_indent==0


def test_markdown_wrapper_unwraps_without_losing_inner_fences():
    wrapped='````markdown\n'+REPORT+'\n````'
    doc=Document(BytesIO(convert_markdown_to_docx(wrapped)))
    assert any(p.text=='Пример работы' and p.style.name.startswith('Heading') for p in doc.paragraphs)
    assert any(p.text=='#include <vector>' and p.style.name=='BT Code' for p in doc.paragraphs)
    assert not any(p.text.startswith('```bash') for p in doc.paragraphs)


def test_inline_code_at_paragraph_start_survives_export_cleanup():
    doc=Document(BytesIO(scrub_markdown_marks(convert_markdown_to_docx('`#include` и `a ** b` остаются кодом.'))))
    assert doc.paragraphs[0].text=='#include и a ** b остаются кодом.'
