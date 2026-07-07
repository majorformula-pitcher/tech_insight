"""로그인 강제 미들웨어.

settings.REQUIRE_LOGIN 이 True일 때, 미인증 사용자가 보호 페이지에 접근하면
로그인 페이지로 리다이렉트한다. (서버 DEBUG=0 기본 ON, 로컬 DEBUG=1 기본 OFF)

예외 경로(누구나 접근): 로그인/로그아웃, admin(자체 로그인), 정적파일, dev-login.
"""
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect

# 인증 없이 접근 가능한 경로 접두사
# /api : 조회 전용 공개 API — 세션이 아닌 토큰(Bearer)으로 자체 인증하므로 로그인 리다이렉트 제외
EXEMPT_PREFIXES = ("/login", "/logout", "/admin", "/static", "/api")


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "REQUIRE_LOGIN", False) and not request.user.is_authenticated:
            path = request.path
            if not any(path.startswith(p) for p in EXEMPT_PREFIXES):
                return redirect(f"{settings.LOGIN_URL}?next={quote(path)}")
        return self.get_response(request)
