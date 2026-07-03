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

from django.db.models import Q

from insight.embeddings import embed_one
from insight.models import Document, Source

# 너무 흔해서 검색에 도움 안 되는 단어
STOPWORDS = {
    "그리고", "그러나", "하지만", "또는", "이런", "저런", "그런", "있다", "없다",
    "한다", "에서", "으로", "관련", "대한", "위한", "통해", "있는", "되는",
    "the", "and", "for", "with", "this", "that", "은", "는", "이", "가", "을", "를",
    "어떤", "무엇", "영향", "효과", "전망", "현황", "동향", "분석", "연구",
    # 조회 질문에 흔히 섞이는 지시·범용어 (이 코퍼스에선 변별력이 없어 잡음만 됨)
    "데이터", "자료", "정보", "내용", "저장", "저장된", "중에", "중", "관해", "대해",
    "알려줘", "알려", "보여줘", "보여", "출력", "정리", "검색", "찾아", "찾아줘",
    "최근", "관련된", "에는", "에서의",
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


# 한국어 조사 — 토큰 끝에 붙으면 떼어내 어간으로 만든다('데이터를'→'데이터'). 긴 것 우선.
_JOSA = ("으로서", "으로써", "에서는", "에서도", "으로", "에서", "에게", "라고", "이라",
         "에는", "에도", "께서", "처럼", "보다", "마저", "조차", "까지", "부터",
         "은", "는", "이", "가", "을", "를", "에", "의", "로", "와", "과", "도", "만", "랑")


def _strip_josa(w: str) -> str:
    """한글 토큰 끝의 조사를 제거(어간이 2자 이상 남을 때만)."""
    if re.fullmatch(r"[가-힣]+", w):
        for j in _JOSA:
            if w.endswith(j) and len(w) - len(j) >= 2:
                return w[:-len(j)]
    return w


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    out = []
    for w in words:
        w = _strip_josa(w)
        if len(w) >= 2 and w not in STOPWORDS:
            out.append(w)
    return out


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


def retrieve(query: str, top_k: int = 5, source_type=None, filters=None) -> list[dict]:
    """
    질문과 관련된 문서 top_k개를 반환 (벡터+키워드 하이브리드).
    기본 근거 풀은 '논문 + 연구소 블로그'. source_type="news" 면 뉴스를 검색한다.
    source_type 은 문자열 또는 리스트 모두 허용.
    filters(dict=plan, 선택): 하드 슬롯으로 후보를 정확히 거른다(설계: 하드/소프트 분리).
      date_from/date_to(ISO 범위), category, source_type, source_name, author, sort.
      ※ 주제(keyword)는 하드필터로 걸지 않는다 — 아래 의미(벡터)+키워드 랭킹이 담당.
    각 항목: {id, title, summary, authors, affiliations, published_date, score, ...}
    """
    if not query.strip():
        return []

    if source_type is None:
        source_type = [Source.Type.PAPER, Source.Type.BLOG]   # 근거 = 논문 + 블로그
    types = [source_type] if isinstance(source_type, str) else list(source_type)

    f = filters or {}
    VALS = ("id", "title", "summary", "authors", "affiliations",
            "published_date", "url", "source__type", "source__name", "embedding")

    base = Document.objects.filter(source__type__in=types).exclude(summary="")

    # source_type 슬롯: views가 [논문+블로그]와 [뉴스]를 각각 호출하므로,
    # 슬롯이 이 호출의 범위와 안 맞으면 빈 결과(→ 한쪽만 남긴다).
    _STMAP = {"paper": Source.Type.PAPER, "news": Source.Type.NEWS, "blog": Source.Type.BLOG}
    want = _STMAP.get(f.get("source_type"))
    if want is not None:
        if want not in types:
            return []
        base = base.filter(source__type=want)

    # 하드 슬롯 필터 (정확히 일치해야 하는 메타데이터만)
    qs = base
    if f.get("date_from") and f.get("date_to"):
        qs = qs.filter(published_date__range=(f["date_from"], f["date_to"]))
    if f.get("category"):
        qs = qs.filter(category__iexact=f["category"])
    if f.get("source_name"):          # 논문/블로그는 source.name, 뉴스는 authors(매체 도메인)
        s = f["source_name"]
        qs = qs.filter(Q(source__name__icontains=s) | Q(authors__icontains=s))
    if f.get("author"):
        a = f["author"]
        qs = qs.filter(Q(authors__icontains=a) | Q(affiliations__icontains=a))

    cand = list(qs.values(*VALS))
    if not cand:
        return []                     # 명시 조건에 맞는 후보 없음 → 정직하게 빈 결과(views가 안내)

    by_id = {d["id"]: d for d in cand}

    # 주제 랭킹: 잡음·조사를 제거한 핵심어로 벡터+키워드 하이브리드(RRF)
    core = _tokens(query)
    clean_q = " ".join(core) if core else query
    vec = _vector_ranked(clean_q, cand)       # [(id, sim)]
    kw = _keyword_ranked(query, cand)         # [(id, score)]
    fused = {}
    for rank, (doc_id, _) in enumerate(vec):
        fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, (doc_id, _) in enumerate(kw):
        fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    def _date_key(i):
        d = by_id[i]["published_date"]
        return (d is not None, d)             # None(날짜없음)은 뒤로

    if fused and f.get("sort") != "date_desc":
        top_ids = sorted(fused, key=lambda i: -fused[i])[:top_k]     # 관련도순
    elif fused:
        top_ids = sorted(fused, key=_date_key, reverse=True)[:top_k]  # 관련 후보를 최신순
    else:
        # 주제 신호가 없는 순수 필터 조회 → 후보 전체를 최신순으로
        top_ids = sorted(by_id, key=_date_key, reverse=True)[:top_k]

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
            "url": d.get("url", ""),
            "source_type": d.get("source__type", ""),
            "source_name": d.get("source__name", ""),
            "score": round(fused.get(doc_id, 0.0), 5),
        })
    return results
