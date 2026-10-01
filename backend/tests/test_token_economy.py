"""Token economy: stable prompt prefix, sane reasoning defaults, honest accounting."""

from types import SimpleNamespace

from model_context import COMPACT_RATIO, MAX_PROMPT_TOKENS, cached_prompt_tokens, input_budget_tokens
from openai_client import _build_responses_input, _get_reasoning_config
from runtime_context import with_runtime_context

SKILLS = "Скилы уже подобраны под этот ход. Не вызывай load_skill для них повторно."
WEB = "Ниже результаты актуального веб-поиска. Используй их при ответе."


def _chat():
    return [
        {"role": "system", "content": "SYSTEM"},
        {"role": "system", "content": "Пользователь предоставил документ для контекста: a.pdf\nтекст"},
        {"role": "user", "content": "первый вопрос"},
        {"role": "assistant", "content": "первый ответ"},
        {"role": "user", "content": "второй вопрос"},
    ]


def _prefix(input_items, until_text):
    out = []
    for item in input_items:
        if item.get("content") == until_text:
            break
        out.append(item)
    return out


def test_turn_blocks_stay_out_of_the_cached_prefix():
    """A skills or web block that changes between turns must not shift the history."""
    plain = _build_responses_input(_chat())
    with_skills = _build_responses_input(
        with_runtime_context(_chat(), use_skills=False) + [{"role": "system", "content": SKILLS}]
    )
    with_both = _build_responses_input(
        _chat()[:-1] + [{"role": "system", "content": WEB}, {"role": "system", "content": SKILLS}, _chat()[-1]]
    )
    for _, items in (plain, with_skills, with_both):
        texts = [i["content"] for i in items]
        # history keeps its order and the last question is last
        assert texts.index("первый вопрос") < texts.index("первый ответ") < texts.index("второй вопрос")
        assert items[-1]["content"] == "второй вопрос"
    # everything before the last question is identical with or without the per-turn blocks
    base = _prefix(plain[1], "второй вопрос")
    assert [i for i in _prefix(with_both[1], WEB)] == base
    tail = [i["content"] for i in with_both[1][-3:]]
    assert tail == [WEB, SKILLS, "второй вопрос"]
    # instructions are only the first system message
    assert plain[0] == "SYSTEM"


def test_runtime_context_puts_skills_before_last_user_not_at_the_top():
    messages = [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "проверь чертёж по ЕСКД"},
    ]
    out = with_runtime_context(messages, use_skills=True, sandbox=False)
    roles = [m["role"] for m in out]
    assert out[1]["role"] == "system" and "Сегодня" in out[1]["content"]  # date: stable, daily
    skills = [i for i, m in enumerate(out) if str(m["content"]).startswith("Скилы уже подобраны")]
    assert skills and skills[0] == len(out) - 2  # right before the last user message
    assert out[-1]["content"] == "проверь чертёж по ЕСКД" and roles[-1] == "user"
    # history order is untouched
    assert [m["content"] for m in out if m["role"] in {"user", "assistant"}] == ["q1", "a1", "проверь чертёж по ЕСКД"]


def test_sol_default_reasoning_is_medium_and_dial_still_works():
    assert _get_reasoning_config("gpt-6-sol") == {"effort": "medium"}
    assert _get_reasoning_config("gpt-6-sol", "none") == {"effort": "medium"}
    assert _get_reasoning_config("gpt-6-sol", "high") == {"effort": "high"}
    assert _get_reasoning_config("gpt-6-sol", "xhigh") == {"effort": "xhigh"}
    assert _get_reasoning_config("gpt-6-astra") == {"effort": "high"}
    assert _get_reasoning_config("gpt-6-luna") == {"effort": "low"}


def test_prompt_is_capped_below_the_long_context_surcharge():
    from app.billing.plans import LONG_CONTEXT_INPUT

    # The estimator counts 3 chars per token; Russian text runs ~25% heavier in
    # reality. The point where history is compacted must stay under the surcharge.
    assert MAX_PROMPT_TOKENS * COMPACT_RATIO * 1.25 < LONG_CONTEXT_INPUT
    for mode in ("auto", "gpt-6-sol", "gpt-6-astra", "director", "deepseek-v4-pro"):
        assert input_budget_tokens(mode) <= MAX_PROMPT_TOKENS
    # Kimi has a smaller real window and stays below the cap on its own
    assert input_budget_tokens("kimi-k2.6") < MAX_PROMPT_TOKENS


def test_cached_prompt_tokens_reads_each_provider_shape():
    assert cached_prompt_tokens(None) == 0
    assert cached_prompt_tokens(SimpleNamespace(prompt_cache_hit_tokens=900, prompt_tokens=1000)) == 900  # DeepSeek
    assert cached_prompt_tokens(SimpleNamespace(cached_tokens=640)) == 640  # Moonshot
    assert cached_prompt_tokens(SimpleNamespace(prompt_tokens_details=SimpleNamespace(cached_tokens=512))) == 512
    assert cached_prompt_tokens({"prompt_tokens_details": {"cached_tokens": 128}}) == 128
    assert cached_prompt_tokens(SimpleNamespace(prompt_tokens=1000)) == 0


def test_deepseek_and_kimi_report_cache_to_usage():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "bot_core"
    for name in ("deepseek_client.py", "kimi_client.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "cached_prompt_tokens" in source and "total_cached_tokens" in source, name
        assert "total_output_tokens)" not in source.replace("total_output_tokens, total_cached_tokens)", ""), name


def test_cost_table_uses_each_models_cached_rate():
    from app.billing.costs import model_cost_usd

    one_m = 1_000_000
    assert round(model_cost_usd("gpt-6-sol", one_m, 0, cached_input_tokens=one_m), 4) == 0.10
    assert round(model_cost_usd("kimi-k2.6", one_m, 0), 4) == 0.95
    assert round(model_cost_usd("kimi-k2.6", one_m, 0, cached_input_tokens=one_m), 4) == 0.16
    assert round(model_cost_usd("gpt-6-luna", 0, one_m), 4) == 0.50
