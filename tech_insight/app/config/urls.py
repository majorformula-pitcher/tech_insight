"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from dashboard import views as dashboard_views

urlpatterns = [
    path('admin/', admin.site.urls),
    # 로그인/로그아웃 (회원가입 없음 — 계정은 admin에서 직접 생성)
    # 로그인 성공 시 staff는 /admin/, 일반 사용자는 /chat/ 으로 (RoleLoginView)
    path('login/', dashboard_views.RoleLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', include('dashboard.urls')),
    path('chat/', include('chatbot.urls')),
]
