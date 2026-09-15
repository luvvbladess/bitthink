"""
ponytail self-check for reduce_heavy_context (Map-Reduce for large documents).

Regression test for the truncation bug: the Map step used to do
`doc_content[:200000]` instead of splitting into chunks, so anything past the
first 200k chars of a document was silently dropped before the model ever saw
it. This plants a marker string well past that old cutoff and asserts it
survives through to the final reduced context.

get_chat_response is monkeypatched to a no-op echo so this runs without any
real LLM API keys or network calls.

Run: python scripts/selfcheck_map_reduce.py
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "app" / "bot_core"))
sys.path.insert(0, str(BACKEND_DIR))

import handlers.core as core  # noqa: E402


async def _fake_get_chat_response(prompt, model=None, user_id=None, use_tools=False):
    # Echo the chunk back verbatim instead of calling a real LLM, so the
    # marker string's survival through Map-Reduce can be checked exactly.
    chunk_text = prompt[-1]["content"]
    return chunk_text, [], "", []


async def main() -> None:
    core.get_chat_response = _fake_get_chat_response

    marker = "MARKER_AT_400000_XYZZY"
    doc = ("a" * 400000) + marker + ("b" * (750000 - 400000 - len(marker)))  # 750000 chars total
    assert len(doc) == 750000

    heavy_doc_message = {
        "role": "system",
        "content": f"Пользователь предоставил документ для контекста: big_statement.txt\n\nСодержание:\n{doc}",
    }
    trailing_user_message = {"role": "user", "content": "Проверь документ целиком"}
    messages = [heavy_doc_message, trailing_user_message]

    result = await core.reduce_heavy_context(
        messages, "Проверь документ целиком", status_msg=None, user_id=1, model="kimi-k2.6",
    )

    combined = "\n".join(m.get("content", "") for m in result)
    assert marker in combined, "Marker past the old 200k truncation cutoff was lost — Map-Reduce is truncating again"

    print("OK: marker at char 400000 of a 750000-char document survived reduce_heavy_context")


if __name__ == "__main__":
    asyncio.run(main())
