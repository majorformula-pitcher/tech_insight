"""
실시간 웹 검색 — 질문과 관련된 최신 외부 정보를 가져온다 (무료, API 키 불필요).

로컬 LLM(EXAONE)은 스스로 웹을 검색할 수 없으므로, 우리 코드가 대신 검색해
결과를 근거로 전달한다. 검색은 DuckDuckGo(ddgs), 본문 보강은 기존 크롤러 재활용.

흐름: 질문 → DuckDuckGo 상위 결과(제목/URL/요약) → 상위 N개는 본문 일부까지 페치.
"""
from __future__ import annotations


def search_web(query: str, max_results: int = 5, region: str = "kr-kr",
               fetch_top: int = 2) -> list[dict]:
    """질문으로 웹 검색. [{title, url, snippet, body}] 반환. 실패 시 빈 리스트."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        from ddgs import DDGS
    except Exception:  # noqa: BLE001 — 라이브러리 미설치 등
        return []

    rows = []
    try:
        with DDGS() as d:
            rows = list(d.text(query, region=region, max_results=max_results))
    except Exception:  # noqa: BLE001 — 네트워크/차단 등
        return []

    results = []
    for r in rows:
        url = r.get("href") or r.get("url") or ""
        if not url:
            continue
        results.append({
            "title": (r.get("title") or "").strip(),
            "url": url,
            "snippet": (r.get("body") or "").strip(),
            "body": "",
        })

    # 상위 fetch_top개는 본문 일부까지 가져와 근거를 풍부하게
    if fetch_top > 0:
        try:
            from insight.collectors.news import extract_article
        except Exception:  # noqa: BLE001
            extract_article = None
        if extract_article:
            for r in results[:fetch_top]:
                try:
                    art = extract_article(r["url"], timeout=8)
                    body = (art.get("body") or "").strip()
                    if body:
                        r["body"] = body[:1500]
                except Exception:  # noqa: BLE001
                    pass
    return results
