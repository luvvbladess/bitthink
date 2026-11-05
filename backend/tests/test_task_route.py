from app.services.task_route import ROUTE_INSTRUCTIONS, parse_route, rule_route

PROJECTS = [{'product_id': 'p1', 'artifact': 'product-p1.zip'}]


def test_instructions_default_to_an_answer_when_the_request_is_ambiguous():
    assert 'выбирай reply' in ROUTE_INSTRUCTIONS
    assert 'создай современный лендинг' in ROUTE_INSTRUCTIONS
    assert '"action":"reply"' in ROUTE_INSTRUCTIONS


def test_parser_reads_the_model_decision_and_ignores_markdown():
    raw = '```json\n{"action":"reply","goal":"промпт для сайта","workspace_id":""}\n```'
    assert parse_route(raw, PROJECTS) == {'action': 'reply', 'goal': 'промпт для сайта', 'workspace_id': ''}
    built = parse_route('{"action":"product","goal":"сайт по промпту","workspace_id":"p1"}', PROJECTS)
    assert built['action'] == 'product' and built['workspace_id'] == ''
    revised = parse_route('{"action":"revise","goal":"крупнее шрифт","workspace_id":"missing"}', PROJECTS)
    assert revised == {'action': 'revise', 'goal': 'крупнее шрифт', 'workspace_id': 'p1'}
    assert parse_route('{"action":"revise","goal":"правка"}', [])['action'] == 'reply'
    assert parse_route('не json', PROJECTS) is None
    assert parse_route('{"action":"dance"}', PROJECTS) is None


def test_rules_do_not_treat_a_prompt_about_a_site_as_a_build():
    assert rule_route('сделай промпт для сайта кофейни')['action'] == 'reply'
    assert rule_route('Сделай сайт по этому промпту')['action'] == 'product'
    assert rule_route('шрифты бы покрупнее')['action'] == 'defer'
