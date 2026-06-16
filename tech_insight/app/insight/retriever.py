"""
관련 문서 검색 — 질문과 관련된 논문/뉴스를 찾는다.

하이브리드: ① 의미 기반 벡터 검색(bge-m3 임베딩 코사인)
           ② 키워드(단어 토큰) 검색
두 결과를 RRF(Reciprocal Rank Fusion)로 결합해 상위 top_k를 반환한다.
임베딩이 없거나 임베딩 서버가 죽으면 자동으로 키워드 검색만으로 동작(폴백).

retrieve() 인터페이스는 그대로 유지하므로 호출측(views) 수정 불필요.
"""
import re

import numpy as np

from insight.embeddings import embed_one
from insight.models import Document, Source

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

RRF_K = 60   # RRF 상수 (클수록 상위 순위 가중 완화)


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    return [w for w in words if len(w) >= 2 and w not in STOPWORDS]


def _expand(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for t in tokens:
        if t in SYNONYMS:
            expanded.update(SYNONYMS[t])
    return expanded


def _keyword_ranked(query, cand):
    """키워드 점수 내림차순 [(id, score), ...]."""
    q_core = set(_tokens(query))
    if not q_core:
        return []
    q_tokens = _expand(q_core)
    scored = []
    for d in cand:
        haystack = f"{d['title']} {d['summary']} {d['authors']} {d['affiliations']}"
        d_tokens = set(_tokens(haystack))
        overlap = q_tokens & d_tokens
        if not overlap:
            continue
        title_tokens = set(_tokens(d["title"]))
        score = len(overlap) + len(q_core & title_tokens)
        scored.append((d["id"], score))
    scored.sort(key=lambda x: -x[1])
    return scored


def _vector_ranked(query, cand):
    """의미 유사도 내림차순 [(id, sim), ...]. 임베딩 없거나 실패 시 빈 리스트."""
    try:
        qv = embed_one(query)
    except Exception:  # noqa: BLE001
        return []
    if not qv:
        return []
    qn = np.asarray(qv, dtype=np.float32)
    qn = qn / (np.linalg.norm(qn) + 1e-9)

    ids, mats = [], []
    for d in cand:
        emb = d.get("embedding")
        if emb:
            ids.append(d["id"])
            mats.append(np.frombuffer(emb, dtype=np.float32))
    if not ids:
        return []
    M = np.vstack(mats).astype(np.float32)
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    sims = M @ qn
    order = np.argsort(-sims)
    return [(ids[i], float(sims[i])) for i in order]


def retrieve(query: str, top_k: int = 5, source_type=None) -> list[dict]:
    """
    질문과 관련된 문서 top_k개를 반환 (벡터+키워드 하이브리드).
    기본 근거 풀은 '논문 + 연구소 블로그'. source_type="news" 면 뉴스를 검색한다.
    source_type 은 문자열 또는 리스트 모두 허용.
    각 항목: {id, title, summary, authors, affiliations, published_date, score, ...}
    """
    if not query.strip():
        return []

    if source_type is None:
        source_type = [Source.Type.PAPER, Source.Type.BLOG]   # 근거 = 논문 + 블로그
    types = [source_type] if isinstance(source_type, str) else list(source_type)

    cand = list(Document.objects
                .filter(source__type__in=types)
                .exclude(summary="")
                .values("id", "title", "summary", "authors", "affiliations",
                        "published_date", "embedding"))
    if not cand:
        return []

    vec = _vector_ranked(query, cand)         # [(id, sim)]
    kw = _keyword_ranked(query, cand)         # [(id, score)]

    # RRF 결합: 각 랭킹에서의 순위로 점수화 후 합산
    fused = {}
    for rank, (doc_id, _) in enumerate(vec):
        fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, (doc_id, _) in enumerate(kw):
        fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    if not fused:
        return []

    by_id = {d["id"]: d for d in cand}
    top_ids = sorted(fused, key=lambda i: -fused[i])[:top_k]
    results = []
    for doc_id in top_ids:
        d = by_id[doc_id]
        results.append({
            "id": d["id"],
            "title": d["title"],
            "summary": d["summary"],
            "authors": d["authors"],
            "affiliations": d["affiliations"],
            "published_date": d["published_date"],
            "score": round(fused[doc_id], 5),
        })
    return results
