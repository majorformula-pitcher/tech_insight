"""Tech Insight 조회용 MCP 서버 — 조회 전용 REST API(②)의 얇은 래퍼.

Claude(Desktop/Code)에서 기술문서 코퍼스(논문·블로그·뉴스)를 도구로 검색·조회한다.
답변 생성·분석은 Claude가 하고, 이 서버는 **데이터만 반환**한다(자체 LLM 없음 → 비용 없음).
로직은 전부 REST API에 있고, 여기서는 HTTP 호출을 MCP tool로 노출하기만 한다.

환경변수:
    TECHINSIGHT_API   = http://<서버>/api/v1      (조회 전용 API 베이스 URL)
    TECHINSIGHT_TOKEN = <발급 토큰>               (Authorization: Bearer)

설치:  pip install mcp httpx
실행:  python techinsight_mcp.py                 (stdio 전송 — Claude Desktop/Code)
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("TECHINSIGHT_API", "http://168.107.27.0:8000/api/v1").rstrip("/")
TOKEN = os.environ.get("TECHINSIGHT_TOKEN", "")
_HEADERS = {"Authorization": f"Bearer {TOKEN}"}

mcp = FastMCP("tech-insight")


def _get(path: str, params: dict | None = None):
    """API GET 호출 → JSON. 실패 시 에러 메시지를 dict로 반환(도구가 죽지 않게)."""
    try:
        r = httpx.get(f"{API}{path}", params=params or {}, headers=_HEADERS, timeout=30)
        if r.status_code == 401:
            return {"error": "인증 실패 — TECHINSIGHT_TOKEN 확인 필요"}
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:  # noqa: BLE001
        return {"error": f"API 호출 실패: {e}"}


@mcp.tool()
def search_documents(query: str = "", category: str = "", source_type: str = "",
                     date_from: str = "", date_to: str = "", limit: int = 10) -> dict:
    """기술문서(논문·블로그·뉴스)를 의미검색해 요약+메타데이터+원문 링크를 반환한다.
    원문 전문은 제공하지 않는다(저작권). 필요하면 결과의 url로 원문을 안내하라.

    Args:
        query: 검색 주제(예: "휴머노이드 로봇"). 비우면 필터 조건으로 최신순 목록.
        category: AI, Robot, Security, Data, IT, Display, 기타 중 하나(선택).
        source_type: paper, blog, news 중 하나(선택, 비우면 전체).
        date_from: 시작일 YYYY-MM-DD(선택). date_to와 함께 지정해야 적용.
        date_to: 종료일 YYYY-MM-DD(선택).
        limit: 최대 건수(1~50, 기본 10).
    """
    params = {"q": query, "category": category, "type": source_type,
              "from": date_from, "to": date_to, "limit": limit}
    return _get("/search/", {k: v for k, v in params.items() if v})


@mcp.tool()
def get_document(doc_id: int) -> dict:
    """문서 1건의 상세(제목·저자·요약·카테고리·발행일·원문 링크)를 반환한다.
    원문 전문(raw_text)은 포함하지 않는다."""
    return _get(f"/documents/{doc_id}/")


@mcp.tool()
def list_metadata() -> dict:
    """검색에 쓸 수 있는 카테고리 목록·출처유형·전체 문서 수를 반환한다.
    사용자 질문에 맞는 category/source_type를 고를 때 참고하라."""
    return _get("/meta/")


if __name__ == "__main__":
    mcp.run()
