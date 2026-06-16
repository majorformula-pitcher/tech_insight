"""대시보드 뷰 — 정적 분석 데이터에 DB 실시간 지표를 합쳐 렌더링한다."""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from insight.dashboard_data import get_dashboard_context
from insight.unified_data import build_unified_metrics, build_topic_analysis

STATIC_JSON = Path(__file__).resolve().parent / "static_data.json"


def index(request):
    # 1) 기존 정적 분석 데이터(키워드/주제 등) 로드
    static_data = json.loads(STATIC_JSON.read_text(encoding="utf-8"))
    # 2) DB로 계산 가능한 지표를 덮어쓴 최종 데이터 생성 (레벨 2)
    data = get_dashboard_context(static_data)
    return render(request, "dashboard/index.html",
                  {"dashboard_data": data, "active": "journal"})


def unified(request):
    """통합 대시보드 — 전 출처 종합 인사이트 (1단계 집계 + 2단계 토픽/시차)."""
    metrics = build_unified_metrics()
    topics = build_topic_analysis(k=12)     # 2단계: 임베딩 토픽 + 연구→산업 시차
    return render(request, "dashboard/unified.html", {
        "m": metrics, "m_json": json.dumps(metrics, ensure_ascii=False),
        "t": topics, "t_json": json.dumps(topics, ensure_ascii=False),
        "topics_available": topics.get("available", False),
        "active": "unified",
    })


# ==========================================================================
# 🚨🚨🚨 [보안 경고 — 반드시 운영 전 삭제] 🚨🚨🚨
# 누구나(인터넷의 모든 사용자) 비밀번호 없이 admin 슈퍼유저로 자동 로그인됨.
# 즉 공개 서버에서는 아무나 데이터를 보고·수정·삭제할 수 있는 상태다.
# 개발/테스트 편의를 위해 사용자가 '완전 오픈'을 명시적으로 선택했음.
# 제거 방법: 이 함수 + urls.py 의 dev-login 경로 + 로그인 템플릿의 '입장' 버튼 +
#            context_processors.py + settings 의 등록 줄 삭제.
# ==========================================================================
def dev_autologin(request):
    User = get_user_model()
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        return HttpResponseForbidden("슈퍼유저가 없습니다.")
    login(request, user)
    return redirect("/admin/")
