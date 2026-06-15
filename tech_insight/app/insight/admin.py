import re

from django.contrib import admin
from django.db import models
from django.db.models import Count
from django.forms import Textarea
from django.utils.safestring import mark_safe

from .models import (
    Source, Keyword, Document, Chunk,
    JournalDocument, ArxivDocument, ScholarDocument, HFDocument, NewsDocument,
)


# 출처(Source)는 수집기가 자동 생성하므로 admin 메뉴에서는 숨긴다.
# (다시 보이게 하려면 아래 클래스에 @admin.register(Source) 데코레이터만 붙이면 됨)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "is_active", "document_count")
    list_filter = ("type", "is_active")
    search_fields = ("name",)

    @admin.display(description="문서 수")
    def document_count(self, obj):
        return obj.documents.count()


# 키워드(Keyword)는 대시보드 트렌드 분류용으로 설계만 해둔 미사용 기능이라 메뉴에서 숨긴다.
# (대시보드에 붙일 때 아래 클래스에 @admin.register(Keyword) 데코레이터만 붙이면 됨)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "lifecycle")
    list_filter = ("lifecycle", "category")
    search_fields = ("name",)


class ChunkInline(admin.TabularInline):
    model = Chunk
    extra = 0
    fields = ("order", "text", "embedding_id")
    readonly_fields = ("order", "text")


class DocumentAdmin(admin.ModelAdmin):
    """출처별 프록시 admin의 공통 베이스. 직접 등록하지 않는다.
    source_name 을 지정한 하위 admin이 해당 출처 문서만 보여준다."""
    source_name = None  # 하위 클래스에서 출처 이름 지정

    list_display = ("title", "published_date", "metric", "status", "authors")
    list_filter = ("status",)
    search_fields = ("title", "authors", "affiliations", "raw_text")
    date_hierarchy = "published_date"
    filter_horizontal = ("keywords",)
    inlines = [ChunkInline]
    readonly_fields = ("created_at", "summary_bullets")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if self.source_name:
            qs = qs.filter(source__name=self.source_name)
        return qs

    # 편집 화면 구성: 본문 원문(raw_text)은 fieldsets 에서 제외해 화면에서 숨긴다.
    # (DB에는 그대로 남아 챗봇/검색용으로 보존됨)
    # 원문 PDF는 저작권(공중송신·배포) 문제로 웹 제공하지 않는다 — 요약만 노출.
    fieldsets = (
        ("기본 정보", {
            "fields": ("source", "title", "authors", "affiliations",
                       "published_date", "metric", "status"),
        }),
        ("AI 요약", {
            # summary_bullets: 문장별 불릿 읽기용 표시(읽기 전용)
            # 편집은 엑셀 재적재로 하므로 편집칸(summary)은 화면에서 제외.
            "fields": ("summary_bullets",),
        }),
        ("출처 메타", {
            "fields": ("url", "file_path"),
            "description": "본문 텍스트는 챗봇·검색용으로 DB에만 보관하며 화면에 노출하지 않습니다. "
                           "원문 PDF는 저작권상 웹 제공하지 않습니다(요약만 제공).",
        }),
        ("키워드 · 메타", {
            "fields": ("keywords", "created_at"),
            "classes": ("collapse",),
        }),
    )

    # AI 요약 편집칸을 넓게
    formfield_overrides = {
        models.TextField: {
            "widget": Textarea(attrs={
                "rows": 8,
                "class": "readable-textarea",
            })
        },
    }

    @admin.display(description="AI 요약")
    def summary_bullets(self, obj):
        """요약을 문장 단위로 끊어 불릿(•) 리스트로 보여준다(읽기 전용)."""
        if not obj.summary:
            return "—"
        # 마침표/물음표/느낌표 뒤에서 문장 분리
        sentences = re.split(r"(?<=[.!?])\s+", obj.summary.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        # admin CSS가 ul 불릿을 죽이므로, 불릿 문자를 직접 넣고 flex로 정렬한다.
        rows = "".join(
            '<div style="display:flex;gap:10px;margin-bottom:12px;align-items:flex-start;">'
            '<span style="color:#4f6ef7;font-size:20px;line-height:1.5;flex-shrink:0;">•</span>'
            f'<span style="flex:1;">{s}</span>'
            '</div>'
            for s in sentences
        )
        return mark_safe(
            '<div style="font-size:17px;line-height:1.7;color:#2b2f3a;max-width:860px;'
            'padding:6px 0;">' + rows + '</div>'
        )


# ── 출처별 프록시 admin 등록 (왼쪽 메뉴를 출처별로 분리) ──────────────
@admin.register(JournalDocument)
class JournalDocumentAdmin(DocumentAdmin):
    source_name = "정보과학회지"
    list_display = ("title", "published_date", "affiliations", "status")


@admin.register(ArxivDocument)
class ArxivDocumentAdmin(DocumentAdmin):
    source_name = "arXiv"


@admin.register(ScholarDocument)
class ScholarDocumentAdmin(DocumentAdmin):
    source_name = "Semantic Scholar"


@admin.register(HFDocument)
class HFDocumentAdmin(DocumentAdmin):
    source_name = "HF Papers"


@admin.register(NewsDocument)
class NewsDocumentAdmin(DocumentAdmin):
    source_name = "뉴스"
    list_display = ("title", "published_date", "category", "status", "authors")
    list_filter = ("status", "category")


# ── 왼쪽 메뉴(앱 모델) 표시 순서 지정 ───────────────────────────────
# Django admin은 기본적으로 모델을 이름 알파벳순으로 정렬한다.
# 출처를 논리적 순서(국내→해외→뉴스→출처/키워드)로 보이도록 정렬을 덮어쓴다.
_MODEL_ORDER = ["정보과학회지", "HuggingFace Papers", "arXiv", "Semantic Scholar", "뉴스"]
# 프록시 모델 → 실제 출처 이름 (문서 수 집계용)
_PROXY_SOURCE = {
    "JournalDocument": "정보과학회지",
    "ArxivDocument": "arXiv",
    "ScholarDocument": "Semantic Scholar",
    "HFDocument": "HF Papers",
    "NewsDocument": "뉴스",
}
_orig_get_app_list = admin.AdminSite.get_app_list


def _ordered_get_app_list(self, request, app_label=None):
    app_list = _orig_get_app_list(self, request, app_label)
    # Django가 표시명 첫 글자를 대문자화(arXiv→ArXiv)하므로 소문자로 비교한다.
    rank = {name.lower(): i for i, name in enumerate(_MODEL_ORDER)}
    # 출처별 문서 수를 한 번에 집계
    try:
        counts = {r["source__name"]: r["c"] for r in
                  Document.objects.values("source__name").annotate(c=Count("id"))}
    except Exception:  # noqa: BLE001
        counts = {}
    for app in app_list:
        app["models"].sort(key=lambda m: rank.get(m["name"].lower(), 999))
        for m in app["models"]:
            src = _PROXY_SOURCE.get(m["object_name"])
            m["doc_count"] = counts.get(src) if src else None
    return app_list


admin.AdminSite.get_app_list = _ordered_get_app_list
