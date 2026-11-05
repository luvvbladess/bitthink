import pytest
from app.config import get_settings
from app.services.answer_quality import answer_quality_note
import director_router as dr

@pytest.mark.parametrize('task', ['Почему спорят о причинах падения Римской империи?', 'Сравни философию Канта и утилитаризм', 'Разбери Python код и объясни ошибку'])
def test_specialist_synthesis_keeps_quality(task):
    assert dr._select_composer_model(task, [{'status':'ok', 'model':'gpt-6-sol', 'result':'Findings'}]) == dr.QUALITY_COMPOSER_MODEL

def test_simple_synthesis_keeps_economy():
    assert dr._select_composer_model('Перечисли найденные файлы', [{'status':'ok', 'model':'gpt-6-luna', 'result':'a.txt'}]) == dr.ECONOMY_COMPOSER_MODEL

def test_quality_contract_includes_code_evidence():
    assert 'не запускалось' in answer_quality_note('Разбери Python код')
