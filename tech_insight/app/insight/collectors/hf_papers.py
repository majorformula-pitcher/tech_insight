"""
Hugging Face Daily Papers 수집기 — 추천수 기반 '화제의' 논문.

매일 커뮤니티가 추천·투표한 화제의 arXiv 논문 목록을 가져온다.
인용수(검증된 권위)와 달리, '지금 주목받는 최신 연구'를 포착한다.

API: https://huggingface.co/api/daily_papers (무료, 키 불필요)
 - 날짜 미지정: 최신 ~50편
 - ?date=YYYY-MM-DD: 해당 날짜의 논문 (하루 ~25~50편)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

API_URL = "https://huggingface.co/api/daily_papers"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36"


def _parse_rows(rows, min_upvotes: int) -> list[dict]:
    """daily_papers 응답(rows)을 카드 dict 리스트로 변환 (추천수 필터)."""
    items = []
    for row in rows or []:
        p = row.get("paper") or {}
        arxiv_id = p.get("id") or ""
        upvotes = p.get("upvotes") or 0
        if not arxiv_id or upvotes < min_upvotes:
            continue
        abstract = (p.get("summary") or "").strip()
        if not abstract:
            continue
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or []))
        pub = (row.get("publishedAt") or p.get("publishedAt") or "")[:10] or None
        if pub and (len(pub) != 10 or pub[4] != "-"):
            pub = None
        items.append({
            "title": (p.get("title") or row.get("title") or "").strip(),
            "abstract": abstract,
            "authors": authors[:500],
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "published_date": pub,
            "upvotes": upvotes,
            "metric": f"HF 추천 {upvotes}",
        })
    return items


def _get(params=None):
    resp = requests.get(API_URL, params=params, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    return resp.json() or []


def fetch_trending(limit: int = 15, min_upvotes: int = 10, days: int = 1) -> list[dict]:
    """화제 논문을 추천수 내림차순으로.
    days=1: 최신 목록(~50편)만. days>1: 오늘부터 과거 days일치를 모아 중복 제거."""
    if days <= 1:
        items = _parse_rows(_get(), min_upvotes)
    else:
        today = datetime.now(timezone.utc).date()
        seen, items = set(), []
        for i in range(days):
            d = (today - timedelta(days=i)).isoformat()
            try:
                rows = _get({"date": d})
            except Exception:  # noqa: BLE001
                continue
            for it in _parse_rows(rows, min_upvotes):
                if it["url"] in seen:
                    continue
                seen.add(it["url"])
                items.append(it)

    items.sort(key=lambda x: -x["upvotes"])
    return items[:limit]
