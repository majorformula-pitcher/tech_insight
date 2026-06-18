"""
요약이 빈 블로그 문서(DeepMind/BAIR/Microsoft Research)를 엑셀로 내보낸다.
Claude Cowork 가 raw_text(영문 본문)를 읽고 summary 열만 채워 넣게 하기 위한 export.

import 시 id 로 매칭하므로 id 열은 절대 수정/삭제하지 말 것.

사용:
    python export_blogs.py                # 기본 경로로 저장
    python export_blogs.py 출력경로.xlsx  # 경로 지정
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import openpyxl
from django.db.models import Q
from insight.models import Document

OUT = sys.argv[1] if len(sys.argv) > 1 else "../data_source/scripts/blogs_export.xlsx"
# 5개 블로그 전체를 Cowork(Claude)로 통일 요약 — 기존 EXAONE 요약 여부와 무관하게 전부 내보내되
# summary 는 빈칸으로 둔다(Cowork 가 새로 작성).
SOURCES = ["Anthropic", "OpenAI", "DeepMind", "Microsoft Research", "BAIR"]
COLS = ["id", "source", "title", "published_date", "url", "raw_text", "summary"]

qs = (Document.objects
      .filter(source__name__in=SOURCES)
      .select_related("source")
      .order_by("source__name", "-published_date", "id"))

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "blogs"
ws.append(COLS)

n = 0
per = {}
for d in qs:
    ws.append([
        d.id,
        d.source.name,
        d.title,
        d.published_date.isoformat() if d.published_date else "",
        d.url,
        (d.raw_text or "")[:30000],   # 셀 길이 안전선
        "",                           # summary 는 Cowork 가 채울 빈칸
    ])
    n += 1
    per[d.source.name] = per.get(d.source.name, 0) + 1

wb.save(OUT)
print(f"[export 완료] {n}건 → {os.path.abspath(OUT)}")
for s in SOURCES:
    print(f"   {s:22} {per.get(s, 0)}건")
