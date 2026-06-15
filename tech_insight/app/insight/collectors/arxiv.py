"""
arXiv 논문 자동 수집기.

arXiv 공식 Atom API(export.arxiv.org)로 분야별 최신 논문을 조회한다.
웹 크롤링이 아니라 공식 API라 차단·파싱 문제가 없다.

흐름: 분야(cs.*) 지정 → 최신순 논문 목록(제목/초록/저자/URL) → (한국어 요약은 호출측에서).
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")

PDF_URL = "https://arxiv.org/pdf/{}"
_BAD_FN = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_ABS_ID = re.compile(r"arxiv\.org/abs/([^/?#]+)", re.IGNORECASE)


def arxiv_id_from_url(url: str) -> str:
    """arXiv abs URL에서 논문 ID 추출. 예: .../abs/2307.09288 → 2307.09288"""
    m = _ABS_ID.search(url or "")
    return _VER.sub("", m.group(1)) if m else ""


def sanitize_filename(name: str, maxlen: int = 120) -> str:
    """파일명으로 못 쓰는 문자 제거 + 길이 제한."""
    name = _BAD_FN.sub(" ", name or "").strip()
    name = _WS.sub(" ", name)
    return name[:maxlen].strip()


def download_pdf(arxiv_id: str, dest_dir: str, title: str = "", timeout: int = 60) -> str | None:
    """arXiv PDF를 dest_dir에 저장하고 저장된 절대경로 반환. 실패 시 None."""
    if not arxiv_id:
        return None
    os.makedirs(dest_dir, exist_ok=True)
    stem = f"{arxiv_id} {sanitize_filename(title)}".strip() or arxiv_id
    path = os.path.join(dest_dir, stem + ".pdf")
    # 이미 받아둔 정상 파일이면 재사용
    if os.path.exists(path) and os.path.getsize(path) > 2000:
        return path
    resp = requests.get(PDF_URL.format(arxiv_id), headers={"User-Agent": UA},
                        timeout=timeout, stream=True)
    resp.raise_for_status()
    if "pdf" not in resp.headers.get("Content-Type", "").lower():
        return None  # 아직 PDF가 준비 안 됐거나 차단된 경우
    with open(path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    return path if os.path.getsize(path) > 2000 else None

# 수집 분야 (cs.* 카테고리, 한글 표기)
ARXIV_CATEGORIES = [
    ("cs.AI", "AI"),
    ("cs.LG", "머신러닝"),
    ("cs.CL", "자연어처리"),
    ("cs.CR", "보안"),
    ("cs.RO", "로보틱스"),
    ("cs.CV", "비전"),
]

API_URL = "https://export.arxiv.org/api/query"

_WS = re.compile(r"\s+")
_VER = re.compile(r"v\d+$")


def _clean(text: str) -> str:
    """줄바꿈·중복 공백 정리."""
    return _WS.sub(" ", (text or "").strip())


def fetch_category(cat: str, limit: int = 15) -> list[dict]:
    """특정 arXiv 분야의 최신 논문 목록(제출일 내림차순)."""
    params = {
        "search_query": f"cat:{cat}",
        "start": 0,
        "max_results": int(limit),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    # feedparser가 직접 받으면 Windows에서 SSL 인증서 검증에 실패하므로
    # certifi 인증서를 내장한 requests로 받아서 본문을 넘긴다.
    resp = requests.get(API_URL, params=params, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        # id 예: http://arxiv.org/abs/2401.12345v1 → 버전 꼬리표 제거
        raw_id = e.get("id", "")
        abs_url = _VER.sub("", raw_id)
        if abs_url.startswith("http://"):
            abs_url = "https://" + abs_url[len("http://"):]
        authors = ", ".join(a.get("name", "") for a in e.get("authors", []))

        pub = None
        v = e.get("published_parsed")
        if v:
            pub = datetime(*v[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")

        items.append({
            "arxiv_id": abs_url.rsplit("/", 1)[-1],
            "title": _clean(e.get("title", "")),
            "abstract": _clean(e.get("summary", "")),
            "authors": authors[:500],
            "url": abs_url,
            "published_date": pub,
            "category": cat,
        })
    return items


def fetch_all(categories=None, limit_per_cat: int = 15, pause: float = 3.0):
    """여러 분야를 순회 조회. arXiv 권장대로 요청 사이에 간격(기본 3초)을 둔다."""
    cats = categories or [c for c, _ in ARXIV_CATEGORIES]
    out = []
    for i, cat in enumerate(cats):
        out.append((cat, fetch_category(cat, limit_per_cat)))
        if i < len(cats) - 1:
            time.sleep(pause)
    return out
