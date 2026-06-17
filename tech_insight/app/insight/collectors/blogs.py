"""
해외 연구소 블로그 수집기 — Anthropic / OpenAI / DeepMind 등.

연구소 블로그는 권위 있는 연구·발표 콘텐츠라 '근거 풀'(논문과 동급)로 다룬다.
RSS가 있으면 RSS, 없으면(Anthropic 등) 블로그 목록 페이지를 크롤링한다.
본문/이미지 추출은 기존 뉴스 크롤러(extract_article)를 재활용한다.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from insight.collectors.news import fetch_feed, UA, HEADERS

# RSS 제공 블로그 (이름, RSS URL)
BLOG_RSS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/"),
    ("BAIR", "https://bair.berkeley.edu/blog/feed.xml"),
]

# RSS 없는 블로그 — 목록 페이지 크롤링 (이름, 목록 URL, 기사 링크 패턴)
BLOG_CRAWL = [
    ("Anthropic", "https://www.anthropic.com/news", r"/news/[a-z0-9][a-z0-9-]+$"),
]


def fetch_blog_rss(name: str, url: str, limit: int = 10) -> list[dict]:
    """RSS 블로그 기사 목록. 뉴스 fetch_feed 재활용 (title/url/published_date 포함)."""
    return fetch_feed(name, url, limit=limit)


def fetch_blog_crawl(name: str, listing: str, pattern: str, limit: int = 10) -> list[dict]:
    """목록 페이지를 크롤링해 기사 링크·제목을 추출."""
    try:
        r = requests.get(listing, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception:  # noqa: BLE001
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    seen, items = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].split("#")[0]
        if not re.search(pattern, href):
            continue
        url = urljoin(listing, href)
        if url in seen or url.rstrip("/") == listing.rstrip("/"):
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True)[:300]
        items.append({
            "title": title,
            "url": url,
            "published_date": None,           # 본문 페이지에서 보강(없으면 빈값)
            "source_name": name,
            "rss_summary": "",
        })
        if limit and len(items) >= limit:   # limit 0 이하 = 상한 없음
            break
    return items


def fetch_all_blogs(limit_per: int = 8):
    """모든 블로그 소스를 순회 (RSS + 크롤링). [(name, [items]), ...]."""
    out = []
    for name, url in BLOG_RSS:
        try:
            out.append((name, fetch_blog_rss(name, url, limit_per)))
        except Exception:  # noqa: BLE001
            out.append((name, []))
    for name, listing, pat in BLOG_CRAWL:
        try:
            out.append((name, fetch_blog_crawl(name, listing, pat, limit_per)))
        except Exception:  # noqa: BLE001
            out.append((name, []))
    return out
