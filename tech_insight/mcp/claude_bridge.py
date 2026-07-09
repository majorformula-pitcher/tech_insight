"""HTTP MCP 클라이언트 → stdio MCP 브릿지

HTTP MCP 서버(포트 7999)에 연결하고 도구를 stdio로 래핑하여
Claude Desktop에서 사용 가능하게 함.
"""
import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP


HTTP_MCP_URL = os.getenv("HTTP_MCP_URL", "http://127.0.0.1:9000/mcp/")

bridge = FastMCP("tech-insight")


async def _call_http_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """HTTP MCP 서버의 도구를 호출"""
    async with streamable_http_client(HTTP_MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    if result.isError:
        message = _extract_text(result) or str(result)
        raise RuntimeError(f"HTTP MCP tool {tool_name!r} failed: {message}")

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        if set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    text = _extract_text(result)
    if text is None:
        return str(result)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _extract_text(result: Any) -> str | None:
    """결과에서 텍스트 추출"""
    content = getattr(result, "content", None)
    if not content:
        return None

    text_parts = [item.text for item in content if getattr(item, "type", None) == "text"]
    if not text_parts:
        return None
    return "\n".join(text_parts)


@bridge.tool()
async def search_documents(
    query: str = "",
    category: str = "",
    source_type: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 10
) -> Any:
    """기술문서 의미검색"""
    return await _call_http_tool("search_documents", {
        "query": query,
        "category": category,
        "source_type": source_type,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit
    })


@bridge.tool()
async def get_document(doc_id: int) -> Any:
    """문서 상세 조회"""
    return await _call_http_tool("get_document", {"doc_id": doc_id})


@bridge.tool()
async def list_metadata() -> Any:
    """메타데이터 조회"""
    return await _call_http_tool("list_metadata", {})


if __name__ == "__main__":
    bridge.run(transport="stdio")
