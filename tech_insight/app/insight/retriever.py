"""
관련 문서 검색 — 질문/뉴스와 관련된 논문을 찾는다.

현재: 키워드(형태소 대신 단어 토큰) 기반 단순 점수 매칭.
      제목/요약/저자소속에 질문 단어가 많이 겹치는 문서를 상위로.
향후: 임베딩+벡터DB로 교체 가능(인터페이스 retrieve() 유지).
"""
import re

from insight.models import Document

# 너무 흔해서 검색에 도움 안 되는 단어
STOPWORDS = {
    "그리고", "그러나", "하지만", "또는", "이런", "저런", "그런", "있다", "없다",
    "한다", "에서", "으로", "관련", "대한", "위한", "통해", "있는", "되는",
    "the", "and", "for", "with", "this", "that", "은", "는", "이", "가", "을", "를",
}


def _tokens(text: str) -> list[str]:
    """한글/영문/숫자 단어 토큰. 2글자 이상만."""
    words = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    return [w for w in words if len(w) >= 2 and w not in STOPWORDS]


def retrieve(query: str, top_k: int = 5, source_name: str = "정보과학회지") -> list[dict]:
    """
    질문과 관련된 문서 top_k개를 점수순으로 반환.
    각 항목: {document, score, title, summary, authors, affiliations, published_date}
    """
    q_tokens = set(_tokens(query))
    if not q_tokens:
        return []

    results = []
    qs = (Document.objects
          .filter(source__name=source_name)
          .exclude(summary="")
          .values("id", "title", "summary", "authors", "affiliations", "published_date"))

    for d in qs:
        # 제목·요약·저자소속을 합쳐 토큰화하고 질문 토큰과 겹치는 수를 점수로
        haystack = f"{d['title']} {d['summary']} {d['authors']} {d['affiliations']}"
        d_tokens = set(_tokens(haystack))
        overlap = q_tokens & d_tokens
        if not overlap:
            continue
        # 제목에 들어간 단어는 가중치 2배
        title_tokens = set(_tokens(d["title"]))
        score = len(overlap) + len(q_tokens & title_tokens)
        results.append({
            "id": d["id"],
            "title": d["title"],
            "summary": d["summary"],
            "authors": d["authors"],
            "affiliations": d["affiliations"],
            "published_date": d["published_date"],
            "score": score,
            "matched": sorted(overlap),
        })

    results.sort(key=lambda r: -r["score"])
    return results[:top_k]
