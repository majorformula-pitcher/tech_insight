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

# RSS 제공 블로그 (이름, RSS URL) — RSS는 최신글만 노출되므로 전체 확보가 안 되는 곳은
# 아래 사이트맵/아카이브 방식으로 옮겼다. OpenAI 는 RSS 로 이미 전량(999) 확보됨.
BLOG_RSS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
]

# 사이트맵 기반 블로그 (이름, 사이트맵 URL, 기사 경로 패턴, 인덱스 필터) — 전체 글 확보용.
# 인덱스 필터: 사이트맵이 인덱스(sitemapindex)일 때 따라갈 하위 사이트맵 URL 패턴(없으면 "").
BLOG_SITEMAP = [
    ("Anthropic", "https://www.anthropic.com/sitemap.xml",
     r"/(?:news|research)/[a-z0-9][a-z0-9-]+$", ""),
    ("DeepMind", "https://deepmind.google/sitemap.xml",
     r"/blog/[a-z0-9][a-z0-9-]+/?$", ""),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/sitemap_index.xml",
     r"/research/blog/[a-z0-9][a-z0-9-]+/?$", r"post-sitemap"),
]

# RSS·사이트맵 없는 블로그 — 목록 페이지 크롤링 (이름, 목록 URL, 기사 링크 패턴)
BLOG_CRAWL = [
    ("BAIR", "https://bair.berkeley.edu/blog/archive/",
     r"/blog/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/?$"),
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


def _fetch_xml(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        return r.text
    except Exception:  # noqa: BLE001
        return ""


def fetch_blog_sitemap(name: str, sitemap_url: str, pattern: str,
                       limit: int = 0, index_filter: str = "") -> list[dict]:
    """사이트맵에서 기사 URL을 추출. 제목은 본문 페이지에서 보강. limit 0 이하=전체.
    사이트맵이 인덱스(sitemapindex)면 하위 사이트맵을 따라간다.
    index_filter 가 있으면 그 패턴에 맞는 하위 사이트맵만 따라간다(예: post-sitemap)."""
    text = _fetch_xml(sitemap_url)
    if not text:
        return []
    if "<sitemapindex" in text:
        subs = re.findall(r"<loc>([^<]+)</loc>", text)
        if index_filter:
            subs = [s for s in subs if re.search(index_filter, s)]
        texts = [_fetch_xml(s) for s in subs]
    else:
        texts = [text]

    # (url, lastmod) 쌍을 모은다. <lastmod> 가 있으면 발행일·정렬에 활용.
    seen, rows = set(), []
    for t in texts:
        for block in re.findall(r"<url>(.*?)</url>", t, re.S):
            loc_m = re.search(r"<loc>([^<]+)</loc>", block)
            if not loc_m:
                continue
            url = loc_m.group(1).strip()
            if not re.search(pattern, url) or url in seen:
                continue
            seen.add(url)
            lm = re.search(r"<lastmod>([^<]+)</lastmod>", block)
            lastmod = lm.group(1).strip() if lm else ""
            rows.append((url, lastmod))

    # 최신순 정렬(lastmod 내림차순; 없는 건 뒤로) → limit 으로 상위 N 만
    rows.sort(key=lambda r: r[1] or "", reverse=True)
    if limit and limit > 0:
        rows = rows[:limit]

    return [{"title": "", "url": url, "published_date": (lastmod[:10] or None),
             "source_name": name, "rss_summary": ""}
            for url, lastmod in rows]


def fetch_all_blogs(limit_per: int = 8, only: str = ""):
    """모든 블로그 소스를 순회 (RSS + 사이트맵 + 크롤링). [(name, [items]), ...].
    only 가 주어지면 이름이 부분일치하는 출처만 수집."""
    only = (only or "").lower()

    def want(n):
        return (not only) or (only in n.lower())

    out = []
    for name, url in BLOG_RSS:
        if not want(name):
            continue
        try:
            out.append((name, fetch_blog_rss(name, url, limit_per)))
        except Exception:  # noqa: BLE001
            out.append((name, []))
    for name, sm, pat, idxf in BLOG_SITEMAP:
        if not want(name):
            continue
        try:
            out.append((name, fetch_blog_sitemap(name, sm, pat, limit_per, idxf)))
        except Exception:  # noqa: BLE001
            out.append((name, []))
    for name, listing, pat in BLOG_CRAWL:
        if not want(name):
            continue
        try:
            out.append((name, fetch_blog_crawl(name, listing, pat, limit_per)))
        except Exception:  # noqa: BLE001
            out.append((name, []))
    return out
