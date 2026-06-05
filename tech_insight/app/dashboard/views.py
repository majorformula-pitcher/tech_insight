"""대시보드 뷰 — 정적 분석 데이터에 DB 실시간 지표를 합쳐 렌더링한다."""
import json
from pathlib import Path

from django.shortcuts import render

from insight.dashboard_data import get_dashboard_context

STATIC_JSON = Path(__file__).resolve().parent / "static_data.json"


def index(request):
    # 1) 기존 정적 분석 데이터(키워드/주제 등) 로드
    static_data = json.loads(STATIC_JSON.read_text(encoding="utf-8"))
    # 2) DB로 계산 가능한 지표를 덮어쓴 최종 데이터 생성 (레벨 2)
    data = get_dashboard_context(static_data)
    return render(request, "dashboard/index.html", {"dashboard_data": data})
