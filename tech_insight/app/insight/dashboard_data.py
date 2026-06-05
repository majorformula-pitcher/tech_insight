"""
대시보드용 집계 데이터 생성 (레벨 2: 반 동적).

DB에서 '계산 가능한' 값은 여기서 실시간 생성하고,
키워드/주제 등 '분석이 필요한' 값은 기존 정적 대시보드(test/index.html)의
하드코딩 값을 STATIC_FALLBACK에서 가져와 합친다.

레벨 3에서 Claude API로 키워드/주제를 분석해 DB에 채우면,
STATIC_FALLBACK 의존 부분을 점차 DB 생성으로 교체한다.
"""
from __future__ import annotations

from collections import defaultdict

from insight.models import Document, Source


def _month_key(d) -> str:
    """date -> '2026-05' 형식."""
    return f"{d.year:04d}-{d.month:02d}"


def build_db_metrics(source_name: str = "정보과학회지") -> dict:
    """DB에서 계산 가능한 지표를 생성한다."""
    docs = list(
        Document.objects
        .filter(source__name=source_name)
        .exclude(published_date=None)
        .values_list("published_date", "affiliations")
    )

    # 호(월)별 편수 / 연도별 편수
    per_issue: dict[str, int] = defaultdict(int)
    per_year: dict[str, int] = defaultdict(int)
    for pub, _affil in docs:
        per_issue[_month_key(pub)] += 1
        per_year[str(pub.year)] += 1

    issues = sorted(per_issue.keys())

    # Top 기관 (소속이 채워진 경우에만 집계 — 현재는 대부분 비어 있음)
    org_count: dict[str, int] = defaultdict(int)
    for _pub, affil in docs:
        if not affil:
            continue
        for org in (a.strip() for a in affil.split(",")):
            if org:
                org_count[org] += 1
    top_affils = sorted(org_count.items(), key=lambda x: -x[1])[:15]

    return {
        "issues": issues,
        "papers_per_issue": dict(sorted(per_issue.items())),
        "yearly_vol": dict(sorted(per_year.items())),
        "top_affils": top_affils,            # 소속 추출 전이면 빈 리스트
        "total_papers": len(docs),
        "total_issues": len(issues),
        "affil_filled": sum(1 for _p, a in docs if a),  # 소속 채워진 문서 수
    }


def get_dashboard_context(static_data: dict, source_name: str = "정보과학회지") -> dict:
    """
    정적 대시보드 데이터(static_data)에 DB 실시간 지표를 덮어쓴 최종 데이터를 반환.

    - DB로 대체: issues, papers_per_issue, yearly_vol, total_papers, total_issues
    - 조건부 대체: top_affils (소속이 충분히 채워졌을 때만)
    - 그대로 유지: kw_matrix, themes, lifecycles, lag_data 등 분석 기반 값
    """
    data = dict(static_data)  # 얕은 복사 후 일부만 교체
    db = build_db_metrics(source_name)

    data["issues"] = db["issues"]
    data["papers_per_issue"] = db["papers_per_issue"]
    data["yearly_vol"] = db["yearly_vol"]
    data["total_papers"] = db["total_papers"]
    data["total_issues"] = db["total_issues"]

    # 소속이 일정 수준 이상 채워졌을 때만 Top 기관을 DB로 대체
    if db["affil_filled"] >= 20 and db["top_affils"]:
        data["top_affils"] = db["top_affils"]

    return data
