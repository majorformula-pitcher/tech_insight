"""
통합 대시보드 데이터 — 전 출처(논문·블로그·뉴스)를 종합한 지표.

1단계: DB 집계 위주 (출처별 볼륨 / 유형 비율).
2단계: 임베딩 기반 토픽 분석 + 연구→산업 시차.
"""
from django.db.models import Count

from insight.models import Document, Source

TYPE_LABEL = {
    Source.Type.PAPER: "논문",
    Source.Type.BLOG: "연구소 블로그",
    Source.Type.NEWS: "뉴스",
}


def build_unified_metrics() -> dict:
    docs = Document.objects.all()
    total = docs.count()

    # 출처별 문서 수 (많은 순)
    by_source = [
        {"name": r["source__name"], "type": r["source__type"], "count": r["c"]}
        for r in docs.values("source__name", "source__type")
                     .annotate(c=Count("id")).order_by("-c")
    ]

    # 유형별 (논문/블로그/뉴스)
    type_counts = {r["source__type"]: r["c"]
                   for r in docs.values("source__type").annotate(c=Count("id"))}
    by_type = [
        {"label": TYPE_LABEL.get(t, t), "count": type_counts.get(t, 0)}
        for t in [Source.Type.PAPER, Source.Type.BLOG, Source.Type.NEWS]
    ]

    return {
        "total": total,
        "kpi": {
            "papers": type_counts.get(Source.Type.PAPER, 0),
            "blogs": type_counts.get(Source.Type.BLOG, 0),
            "news": type_counts.get(Source.Type.NEWS, 0),
            "sources": Source.objects.count(),
        },
        "by_source": by_source,
        "by_type": by_type,
    }


def _label_clusters(members_by_cluster):
    """클러스터별로 '구별되는' 키워드 라벨 생성 (TF-IDF 유사 가중)."""
    import math
    from collections import Counter
    from insight.retriever import _tokens

    k = len(members_by_cluster)
    cluster_counts, df = [], Counter()
    for members in members_by_cluster:
        c = Counter()
        for m in members:
            for t in set(_tokens(m["title"])):   # 제목 토큰(문서당 중복 제거)
                if len(t) >= 2 and not t.isdigit():
                    c[t] += 1
        cluster_counts.append(c)
        for t in c:
            df[t] += 1

    labels = []
    for c in cluster_counts:
        scored = [(t, cnt * math.log((k + 1) / df[t]))
                  for t, cnt in c.items() if df[t] < k]   # 모든 클러스터에 흔한 단어 제외
        scored.sort(key=lambda x: -x[1])
        labels.append(" · ".join(t for t, _ in scored[:3]) or "(기타)")
    return labels


def _median_date(dates):
    return sorted(dates)[len(dates) // 2] if dates else None


# 국내 연구 출처(한국 학술). 그 외 논문/블로그는 해외 연구로 간주.
DOMESTIC_SOURCES = {"정보과학회지"}
EMERGING_MONTHS = 6   # 최근 N개월을 '신흥' 판단 기준으로 사용


def _recent_cutoff(months=EMERGING_MONTHS):
    from datetime import date
    today = date.today()
    y, m = today.year, today.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


_TOPIC_CACHE = {"key": None, "data": None}


def build_topic_analysis(k: int = 12) -> dict:
    """임베딩 K-means 토픽 클러스터링 + 토픽별 출처 구성 + 연구→산업 시차.
    임베딩된 문서 수가 바뀔 때만 재계산(그 외에는 캐시 반환)."""
    import numpy as np

    embedded_n = Document.objects.exclude(embedding__isnull=True).exclude(summary="").count()
    cache_key = (k, embedded_n)
    if _TOPIC_CACHE["key"] == cache_key:
        return _TOPIC_CACHE["data"]

    rows = list(Document.objects
                .exclude(embedding__isnull=True).exclude(summary="")
                .values("id", "title", "source__type", "source__name",
                        "published_date", "embedding"))
    if len(rows) < k:
        return {"available": False}

    try:
        from sklearn.cluster import KMeans
    except Exception:  # noqa: BLE001
        return {"available": False}

    mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(mat)
    labels = km.labels_

    groups = [[] for _ in range(k)]
    for i, lab in enumerate(labels):
        groups[lab].append(rows[i])
    names = _label_clusters(groups)

    cutoff = _recent_cutoff()
    kr_total = intl_total = 0
    topics = []
    for ci, members in enumerate(groups):
        comp = {"paper": 0, "blog": 0, "news": 0}
        rdates, ndates = [], []
        kr = intl = recent = 0
        for m in members:
            st = m["source__type"]
            if st in comp:
                comp[st] += 1
            if st != "news":   # 연구(논문·블로그)만 국내/해외 구분
                if m["source__name"] in DOMESTIC_SOURCES:
                    kr += 1
                else:
                    intl += 1
            pd = m["published_date"]
            if pd:
                (ndates if st == "news" else rdates).append(pd)
                if pd >= cutoff:
                    recent += 1
        kr_total += kr
        intl_total += intl
        research = comp["paper"] + comp["blog"]
        rmed, nmed = _median_date(rdates), _median_date(ndates)
        lag = None
        if rmed and nmed:
            lag = (nmed.year - rmed.year) * 12 + (nmed.month - rmed.month)
        topics.append({
            "label": names[ci],
            "size": len(members),
            "paper": comp["paper"], "blog": comp["blog"], "news": comp["news"],
            "research": research,
            "research_ratio": round(research / len(members), 2) if members else 0,
            "lag_months": lag,
            "kr": kr, "intl": intl,                          # 국내/해외 연구 건수
            "kr_gap": research >= 8 and kr == 0,             # 해외만 활발한 국내 공백 토픽
            "recent": recent,
            "recent_ratio": round(recent / len(members), 3) if members else 0,
        })
    topics.sort(key=lambda t: -t["size"])
    result = {
        "available": True, "k": k, "topics": topics,
        "kr_total": kr_total, "intl_total": intl_total,
        "emerging_months": EMERGING_MONTHS,
    }
    _TOPIC_CACHE["key"] = cache_key
    _TOPIC_CACHE["data"] = result
    return result
