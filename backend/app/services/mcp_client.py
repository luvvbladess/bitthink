"""Remote Streamable HTTP MCP, using the official SDK and encrypted connectors."""
import asyncio
import json
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from app.services import connectors


def validate_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Для MCP нужен публичный HTTPS-адрес без логина в URL.")
    if parsed.port not in (None, 443):
        raise ValueError("MCP доступен через стандартный HTTPS-порт.")
    from computer_tools import _assert_public_http_url
    return _assert_public_http_url(url)


@asynccontextmanager
async def session_for(user_id: int, connector_id: int):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    loaded = await asyncio.to_thread(connectors.get_secret, user_id, connector_id)
    if not loaded or loaded[0].type != "mcp":
        raise ValueError("MCP-подключение не найдено в вашем аккаунте.")
    _, payload = loaded
    url = await asyncio.to_thread(validate_endpoint, payload["url"])
    headers = {"Authorization": "Bearer " + payload["token"]} if payload.get("token") else {}

    async def guard(request):
        if request.url != httpx.URL(url):
            raise ValueError("MCP не может перенаправить доступ на другой адрес.")
        await asyncio.to_thread(validate_endpoint, str(request.url))

    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(headers=headers, timeout=timeout or 30, auth=auth,
                                 follow_redirects=False, trust_env=False, event_hooks={"request": [guard]})

    async with streamablehttp_client(url, headers=headers, timeout=30, sse_read_timeout=60,
                                     httpx_client_factory=factory) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session, payload


async def discover(user_id: int, connector_id: int) -> dict:
    async with asyncio.timeout(60), session_for(user_id, connector_id) as (session, payload):
        result = await session.list_tools()
        collected = list(result.tools)
        seen = set()
        while result.nextCursor and len(collected) < 100:
            if result.nextCursor in seen:
                raise ValueError("MCP вернул повторяющуюся страницу инструментов.")
            seen.add(result.nextCursor)
            result = await session.list_tools(cursor=result.nextCursor)
            collected.extend(result.tools)
        tools = [{"name": t.name, "description": (t.description or "")[:1200],
                  "inputSchema": t.inputSchema, "enabled": t.name in payload.get("allowed_tools", [])}
                 for t in collected[:100]]
        return {"tools": tools, "transport": "streamable-http"}


async def call(user_id: int, connector_id: int, name: str, arguments: dict) -> str:
    if len(json.dumps(arguments, ensure_ascii=False)) > 32000:
        raise ValueError("Слишком большой запрос MCP.")
    async with asyncio.timeout(90), session_for(user_id, connector_id) as (session, payload):
        if name not in payload.get("allowed_tools", []):
            raise ValueError("Этот MCP-инструмент не включён владельцем подключения.")
        result = await session.call_tool(name, arguments)
        output = json.dumps(result.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
        for secret in connectors.secret_values(user_id):
            output = output.replace(secret, "[секрет скрыт]")
        return output[:12000]
