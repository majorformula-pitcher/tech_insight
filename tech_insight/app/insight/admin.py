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
