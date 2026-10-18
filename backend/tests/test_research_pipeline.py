from app.config import get_settings  # noqa: F401
from director_router import _research_needs_retry, _verify_employee, needs_research


def entry(result, **extra):
    return {'result':result, 'status':'ok', 'search':[{'summary':'https://stats.example/hero'}], **extra}


def test_links_do_not_complete_a_refusal_and_recovery_has_read_tools():
    assert _research_needs_retry([entry('Не смог подтвердить винрейт: данные не найдены.')])
    assert _research_needs_retry([entry('**Честно: сейчас не могу обоснованно назвать лучший тариф.')])
    assert _research_needs_retry([entry('No data', status='error')])
    assert _research_needs_retry([entry('No sources', search=[])])
    assert _verify_employee('Винрейт героя')['web'] is True


def test_useful_partial_answer_does_not_need_an_extra_round():
    assert not _research_needs_retry([entry('Винрейт 51,5% за 7 дней. Точный патч не указан.')])
    assert not _research_needs_retry([entry('Тариф стоит $20. Лимиты третьего варианта подтвердить не удалось.')])


def test_statistics_patch_and_subscription_recommendations_enter_research():
    assert needs_research('какой винрейт у мелисы в млбб в этом патче', False)
    assert needs_research('какой инструмент для ИИ кодинга лучше взять в бюджете 20$', False)
    assert needs_research('что лучше из подписок для разработки', False)
    assert not needs_research('как работает список в Python', False)
    assert not needs_research('привет', False)
