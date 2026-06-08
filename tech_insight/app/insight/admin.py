from django.contrib import admin
from django.db import models
from django.forms import Textarea
from django.utils.html import format_html

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
    readonly_fields = ("created_at", "pdf_download")

    # 편집 화면 구성: 본문 원문(raw_text)은 fieldsets 에서 제외해 화면에서 숨긴다.
    # (DB에는 그대로 남아 챗봇/검색용으로 보존됨)
    fieldsets = (
        ("기본 정보", {
            "fields": ("source", "title", "authors", "affiliations", "published_date", "status"),
        }),
        ("AI 요약", {
            "fields": ("summary",),
        }),
        ("원문", {
            "fields": ("pdf_download", "url", "file_path"),
            "description": "본문 텍스트는 챗봇·검색용으로 DB에 보관되며 화면에는 표시하지 않습니다. 원문은 아래 PDF로 확인하세요.",
        }),
        ("키워드 · 메타", {
            "fields": ("keywords", "created_at"),
            "classes": ("collapse",),
        }),
    )

    # AI 요약 칸을 넓게
    formfield_overrides = {
        models.TextField: {
            "widget": Textarea(attrs={
                "rows": 14,
                "class": "readable-textarea",
            })
        },
    }

    @admin.display(description="PDF 원문")
    def pdf_download(self, obj):
        """PDF 파일이 서버에 있으면 다운로드 링크, 없으면 안내 문구."""
        if not obj.file_path:
            return "— (파일 경로 없음)"
        # /media/원본상대경로 로 접근 (settings 의 MEDIA_URL/MEDIA_ROOT 기준)
        from django.conf import settings
        pdf_full = settings.MEDIA_ROOT / obj.file_path
        if not pdf_full.is_file():
            return format_html(
                '<span style="color:#999;">PDF 미업로드</span> '
                '<span style="font-size:11px;color:#bbb;">({})</span>', obj.file_path
            )
        url = settings.MEDIA_URL + obj.file_path.replace("\\", "/")
        return format_html(
            '<a href="{}" target="_blank" '
            'style="display:inline-block;background:#4f6ef7;color:#fff;'
            'padding:6px 14px;border-radius:8px;text-decoration:none;font-weight:600;">'
            '⬇ PDF 원문 다운로드</a>', url
        )
