"""
Semantic Scholar 논문 수집기 — 인용수 기반 '저명한' 논문.

arXiv는 프리프린트라 품질 지표가 없다. Semantic Scholar는 인용수·게재 학회를
제공하므로, 분야별로 '최근(기본 2023년 이후) + 인용수 상위' 논문을 가져온다.
= 검증된 권위 + 너무 옛 고전만 나오지 않는 균형.

API: https://api.semanticscholar.org/graph/v1/paper/search/bulk (무료, 키 불필요)
"""
from __future__ import annotations

import requests

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
FIELDS = "title,abstract,citationCount,year,authors,externalIds,url,venue"

# 6개 분야 → Semantic Scholar 검색어 (arXiv 카테고리에 대응)
TOPICS = [
    ("cs.AI", "AI", "artificial intelligence"),
    ("cs.LG", "머신러닝", "machine learning"),
    ("cs.CL", "자연어처리", "large language model"),
    ("cs.CR", "보안", "computer security"),
    ("cs.RO", "로보틱스", "robotics"),
    ("cs.CV", "비전", "computer vision"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")


def fetch_top_cited(query: str, limit: int = 10, since_year: int = 2023,
                    min_citations: int = 50) -> list[dict]:
    """검색어 분야에서 인용수 상위 논문 목록(최근 연도 + 최소 인용수 필터)."""
    params = {
        "query": query,
        "fields": FIELDS,
        "sort": "citationCount:desc",
        "year": f"{int(since_year)}-",
        "minCitationCount": int(min_citations),
        "fieldsOfStudy": "Computer Science",  # 타 분야(생물학 등) 고인용 논문 drift 방지
    }
    resp = requests.get(API_URL, params=params, headers={"User-Agent": UA}, timeout=40)
    resp.raise_for_status()
    data = resp.json().get("data") or []

    items = []
    for p in data:
        if len(items) >= limit:
            break
        abstract = (p.get("abstract") or "").strip()
        if not abstract:
            continue  # 요약할 본문이 없으면 제외
        ext = p.get("externalIds") or {}
        arxiv_id = ext.get("ArXiv")
        # arXiv 등재 논문만 채택 → AI/ML/CS 분야로 자연스럽게 한정
        # (생물·의학 저널의 고인용 논문 drift 방지). 대부분의 AI 논문은 arXiv에 있다.
        if not arxiv_id:
            continue
        url = f"https://arxiv.org/abs/{arxiv_id}"
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or []))
        venue = (p.get("venue") or "").strip()
        cites = p.get("citationCount") or 0
        metric = f"인용 {cites:,}회"
        if venue and venue.lower() != "arxiv.org":
            metric += f" · {venue}"

        items.append({
            "title": (p.get("title") or "").strip(),
            "abstract": abstract,
            "authors": authors[:500],
            "url": url,
            "published_date": (f"{p['year']}-01-01" if p.get("year") else None),
            "citations": cites,
            "venue": venue,
            "metric": metric[:80],
        })
    # 인용수 내림차순 보장
    items.sort(key=lambda x: -x["citations"])
    return items
