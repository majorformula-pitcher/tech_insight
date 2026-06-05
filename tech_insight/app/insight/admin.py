from django.contrib import admin
from django.db import models
from django.forms import Textarea

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
    readonly_fields = ("created_at",)

    # 본문 원문(raw_text) 텍스트 창을 읽기 편하게.
    # 세부 스타일은 templates/admin/base_site.html 의 .readable-textarea 에서 관리한다.
    formfield_overrides = {
        models.TextField: {
            "widget": Textarea(attrs={
                "rows": 24,
                "class": "readable-textarea",
            })
        },
    }
