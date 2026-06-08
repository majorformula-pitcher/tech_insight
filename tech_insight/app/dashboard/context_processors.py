"""템플릿 전역 컨텍스트.

[개발 편의용 — 배포 끝나면 settings 의 context_processors 에서 이 줄과 함께 정리]
모든 템플릿에서 {{ is_debug }} 로 DEBUG 여부를 쓸 수 있게 한다. (로그인 '입장' 버튼 노출용)
"""
from django.conf import settings


def debug_flag(request):
    return {"is_debug": settings.DEBUG}
