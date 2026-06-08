import re

from django.contrib import admin
from django.db import models
from django.forms import Textarea
from django.utils.safestring import mark_safe

from .models import Source, Keyword, Document, Chunk


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "is_active", "document_count")
    list_filter = ("type", "is_active")
    search_fields = ("name",)

    @admin.display(description="문서 수")
    def document_count(self, obj):
        return obj.documents.count()


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "lifecycle")
    list_filter = ("lifecycle", "category")
    search_fields = ("name",)


class ChunkInline(admin.TabularInline):
    model = Chunk
    extra = 0
    fields = ("order", "text", "embedding_id")
    readonly_fields = ("order", "text")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "published_date", "status", "authors")
    list_filter = ("status", "source", "source__type")
    search_fields = ("title", "authors", "affiliations", "raw_text")
    date_hierarchy = "published_date"
    filter_horizontal = ("keywords",)
    inlines = [ChunkInline]
    readonly_fields = ("created_at", "summary_bullets")

    # 편집 화면 구성: 본문 원문(raw_text)은 fieldsets 에서 제외해 화면에서 숨긴다.
    # (DB에는 그대로 남아 챗봇/검색용으로 보존됨)
    # 원문 PDF는 저작권(공중송신·배포) 문제로 웹 제공하지 않는다 — 요약만 노출.
    fieldsets = (
        ("기본 정보", {
            "fields": ("source", "title", "authors", "affiliations", "published_date", "status"),
        }),
        ("AI 요약", {
            # summary_bullets: 문장별 불릿 읽기용 표시(읽기 전용)
            # summary: 실제 편집용 원본 텍스트
            "fields": ("summary_bullets", "summary"),
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

    @admin.display(description="요약 (읽기용)")
    def summary_bullets(self, obj):
        """요약을 문장 단위로 끊어 불릿(•) 리스트로 보여준다(읽기 전용)."""
        if not obj.summary:
            return "—"
        # 마침표/물음표/느낌표 뒤에서 문장 분리 (소수점·약어는 대체로 한국어 요약엔 적음)
        sentences = re.split(r"(?<=[.!?])\s+", obj.summary.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        items = "".join(
            f'<li style="margin-bottom:8px;">{s}</li>' for s in sentences
        )
        return mark_safe(
            '<ul style="margin:0;padding-left:22px;font-size:16px;line-height:1.85;'
            'color:#2b2f3a;max-width:840px;list-style:disc;">' + items + '</ul>'
        )
