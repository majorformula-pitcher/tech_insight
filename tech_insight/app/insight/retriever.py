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
    "어떤", "무엇", "영향", "효과", "전망", "현황", "동향", "분석", "연구",
}

# 동의어/유사어 — 질문에 왼쪽 단어가 있으면 오른쪽 단어들도 검색에 포함
SYNONYMS = {
    "반도체": ["메모리", "칩", "hbm", "dram", "gpu", "가속기", "프로세서"],
    "메모리": ["반도체", "hbm", "dram", "스토리지", "낸드"],
    "ai": ["인공지능", "딥러닝", "머신러닝", "llm", "모델"],
    "인공지능": ["ai", "딥러닝", "머신러닝", "llm"],
    "llm": ["언어모델", "거대언어모델", "gpt", "에이전트", "생성"],
    "에이전트": ["agent", "llm", "자율"],
    "보안": ["취약점", "해킹", "악성코드", "공격", "암호"],
    "로봇": ["휴머노이드", "자율주행", "robot"],
    "네트워크": ["5g", "6g", "통신", "엣지"],
    "양자": ["퀀텀", "quantum"],
    "추천": ["개인화", "추천시스템"],
    "의료": ["바이오", "헬스", "신약", "진단"],
}


def _tokens(text: str) -> list[str]:
    """한글/영문/숫자 단어 토큰. 2글자 이상만."""
    words = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    return [w for w in words if len(w) >= 2 and w not in STOPWORDS]


def _expand(tokens: set[str]) -> set[str]:
    """질문 토큰을 동의어로 확장한다."""
    expanded = set(tokens)
    for t in tokens:
        if t in SYNONYMS:
            expanded.update(SYNONYMS[t])
    return expanded


def retrieve(query: str, top_k: int = 5, source_name: str = "정보과학회지") -> list[dict]:
    """
    질문과 관련된 문서 top_k개를 점수순으로 반환.
    각 항목: {document, score, title, summary, authors, affiliations, published_date}
    """
    q_core = set(_tokens(query))      # 질문 원본 토큰 (제목 가중치용)
    if not q_core:
        return []
    q_tokens = _expand(q_core)        # 동의어 확장 토큰 (매칭용)

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
        # 사용자가 실제로 친 단어(q_core)가 제목에 있으면 가중치 추가
        title_tokens = set(_tokens(d["title"]))
        score = len(overlap) + len(q_core & title_tokens)
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
