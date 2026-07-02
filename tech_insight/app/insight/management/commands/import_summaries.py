"""
Claude(또는 사람)가 만든 요약 JSONL을 Document에 반영한다 — 고품질 수동 요약 경로의 2단계.

정보과학회지·HF 논문 등을 Claude로 요약해 넣거나, 기존 요약을 고품질로 교체할 때 쓴다.
요약이 바뀌면 임베딩을 무효화하므로, 이후 embed_documents 를 돌리면 재임베딩된다.

JSONL 각 줄(JSON) — 셋 중 하나:
  {"id": 123, "summary": "..."}                     # 기존 문서 요약 갱신(id 매칭)
  {"url": "https://...", "summary": "..."}           # url 매칭 갱신
  {"source":"HF Papers","title":"...","url":"...","summary":"...",
   "authors":"...","published_date":"2026-01-01","raw_text":"..."}   # 신규 생성

동작: id 또는 url로 기존 문서를 찾으면 요약 갱신, 없으면 source+title로 신규 생성.

사용 예:
    python manage.py import_summaries summaries.jsonl
    python manage.py import_summaries summaries.jsonl --engine Claude
    (이후) python manage.py embed_documents
"""
import json

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from insight.models import Source, Document


class Command(BaseCommand):
    help = "요약 JSONL을 Document에 반영(갱신/생성)한다. 이후 embed_documents 필요."

    def add_arguments(self, parser):
        parser.add_argument("path", help="요약 JSONL 파일 경로")
        parser.add_argument("--engine", default="Claude", help="요약 엔진명 기록 (기본 Claude)")
        parser.add_argument("--source-type", default="paper",
                            choices=["paper", "blog", "news"],
                            help="신규 생성 시 Source 유형 (기본 paper)")

    def handle(self, *args, **o):
        engine = o["engine"]
        n_upd = n_new = n_skip = 0
        with open(o["path"], encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    n_skip += 1
                    continue
                summary = (r.get("summary") or "").strip()
                if not summary:
                    n_skip += 1
                    continue

                doc = None
                if r.get("id"):
                    doc = Document.objects.filter(id=r["id"]).first()
                if not doc and r.get("url"):
                    doc = Document.objects.filter(url=r["url"]).first()

                if doc:
                    doc.summary = summary
                    doc.engine = engine
                    doc.status = Document.Status.ANALYZED
                    # 요약이 바뀌었으니 임베딩 무효화 → embed_documents 가 재임베딩
                    doc.embedding = None
                    doc.embed_model = ""
                    doc.save(update_fields=[
                        "summary", "engine", "status", "embedding", "embed_model"])
                    n_upd += 1
                    continue

                # 신규 생성 — source + title 필요
                src_name = (r.get("source") or "").strip()
                title = (r.get("title") or "").strip()
                if not src_name or not title:
                    n_skip += 1
                    continue
                source, _ = Source.objects.get_or_create(
                    name=src_name, defaults={"type": o["source_type"]})
                Document.objects.create(
                    source=source,
                    title=title[:500],
                    authors=(r.get("authors") or "")[:500],
                    published_date=parse_date(r.get("published_date") or ""),
                    raw_text=r.get("raw_text") or "",
                    summary=summary,
                    category=(r.get("category") or "").strip()[:30],
                    image=(r.get("image") or "").strip()[:1000],
                    url=(r.get("url") or "").strip()[:1000],
                    engine=engine,
                    status=Document.Status.ANALYZED,
                )
                n_new += 1

        self.stdout.write(self.style.SUCCESS(
            f"[요약 반영 완료] 갱신 {n_upd} / 신규 {n_new} / 건너뜀 {n_skip}"))
