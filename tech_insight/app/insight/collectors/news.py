"""
뉴스 RSS 자동 수집기.

흐름: RSS 피드 파싱 → 신규 항목 골라 본문 크롤링 → (요약은 호출측에서) → Document 저장.
ai-bongchae(index.js)의 검증된 노하우를 Python 으로 옮김:
- 다수 RSS 소스, User-Agent 위장, JSON-LD 우선 본문 추출, 매체명 꼬리표 제거.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

# 수집할 RSS 소스 (국내외 기술/AI 뉴스)
RSS_FEEDS = [
    ("로봇신문", "https://www.irobotnews.com/rss/allArticle.xml"),
    ("전자신문-AI", "http://rss.etnews.com/04046.xml"),
    ("The AI", "https://www.newstheai.com/rss/allArticle.xml"),
    ("디지털투데이", "https://www.digitaltoday.co.kr/rss/allArticle.xml"),
    ("AI타임스", "https://www.aitimes.com/rss/allArticle.xml"),
    ("ZDNet Korea", "https://zdnet.co.kr/feed"),
    ("Bloter", "https://www.bloter.net/rss/allArticle.xml"),
    ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("VentureBeat", "https://venturebeat.com/feed"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Google Research", "https://research.google/blog/rss/"),
    ("MIT News", "https://news.mit.edu/rss/feed"),
    ("Wired", "https://www.wired.com/feed/category/business/latest/rss"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}

# 본문이 들어있을 만한 셀렉터 (위에서부터 우선)
BODY_SELECTORS = [
    "article", "main", ".article-content", ".post-content", ".entry-content",
    ".article_body", "#articleBody", ".story-content", ".article-body-content",
]

_MEDIA_TAIL = re.compile(
    r"\s*[-|:]\s*(더밀크|The Miilk|Bloomberg|CNBC|The Verge|NYT|Reuters|"
    r"Financial Times|FT|TechCrunch|VentureBeat|CNET|Wired|ZDNet|블로터|AI타임스|"
    r"로봇신문|전자신문|디지털투데이).*$", re.IGNORECASE)


def clean_title(title: str) -> str:
    """제목 끝의 매체명 꼬리표 제거."""
    if not title:
        return ""
    t = _MEDIA_TAIL.sub("", title).strip()
    # 일반 구분자로 끝에 붙은 매체명 처리
    for sep in (" - ", " | ", " :: "):
        if sep in t:
            t = sep.join(t.split(sep)[:-1]).strip() or t
            break
    return t.strip()


def parse_date(entry) -> str:
    """RSS 항목에서 발행일(YYYY-MM-DD)."""
    for key in ("published_parsed", "updated_parsed"):
        v = entry.get(key)
        if v:
            return datetime(*v[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fetch_feed(name: str, url: str, limit: int = 10) -> list[dict]:
    """RSS 피드 파싱 → 항목 리스트."""
    items = []
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
    except Exception:  # noqa: BLE001
        return items
    for e in feed.entries[:limit]:
        link = (e.get("link") or "").strip()
        title = clean_title(e.get("title") or "")
        if not link or not title:
            continue
        items.append({
            "source_name": name,
            "title": title,
            "url": link,
            "published_date": parse_date(e),
            "rss_summary": (e.get("summary") or "")[:500],
        })
    return items


def extract_article(url: str, timeout: int = 15) -> dict:
    """기사 URL에서 본문 + 대표 이미지를 함께 추출. {'body':..., 'image':...}"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return {"body": "", "image": ""}
    soup = BeautifulSoup(resp.text, "html.parser")
    # 대표 이미지 (og:image)
    image = ""
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        image = og_img["content"].strip()
    return {"body": _extract_body_from_soup(soup), "image": image}


def extract_body(url: str, timeout: int = 15) -> str:
    """기사 URL에서 본문 텍스트만 추출 (하위호환)."""
    return extract_article(url, timeout)["body"]


def _extract_body_from_soup(soup) -> str:

    # 1) JSON-LD articleBody (차단 우회에 강함)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        body = _find_article_body(data)
        if body and len(body) > 200:
            return _clean_text(body)

    # 2) 셀렉터 폴백
    for sel in BODY_SELECTORS:
        el = soup.select_one(sel)
        if el:
            for junk in el.select("script, style, nav, footer, aside, header, button"):
                junk.decompose()
            text = el.get_text(" ", strip=True)
            if len(text) > 200:
                return _clean_text(text)

    # 3) og:description 폴백
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return _clean_text(og["content"])
    return ""


def _find_article_body(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("articleBody"), str) and len(obj["articleBody"]) > 200:
            return obj["articleBody"]
        for v in obj.values():
            r = _find_article_body(v)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _find_article_body(item)
            if r:
                return r
    return None


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[가-힣]{2,4}\s*기자", "", text)
    return text.strip()[:8000]
