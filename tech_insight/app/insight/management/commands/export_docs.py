"""
문서를 요약용 JSONL로 내보낸다 — Claude 수동 고품질 요약 경로의 1단계.

정보과학회지·HF 논문 등 본문(raw_text)이 있는 문서를 뽑아 JSONL로 출력한다.
이 출력을 Claude가 읽고 요약해 import_summaries 로 되넣는다.

각 줄(JSON): {"id","title","url","authors","published_date","raw_text"}
             (raw_text 는 --maxchars 까지 잘라서 출력)

사용 예:
    python manage.py export_docs --source "HF Papers" --only-empty --limit 20
    python manage.py export_docs --source "정보과학회지" --limit 10 > papers.jsonl
"""
import json

from django.core.management.base import BaseCommand

from insight.models import Document


class Command(BaseCommand):
    help = "문서를 요약용 JSONL(제목+본문)로 내보낸다. Claude 요약→import_summaries 용도."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="", help="출처명 부분일치 필터 (예: HF, 정보과학회지)")
        parser.add_argument("--only-empty", action="store_true", help="요약이 비어있는 문서만")
        parser.add_argument("--ids", default="", help="특정 id들만 (쉼표구분)")
        parser.add_argument("--limit", type=int, default=20, help="최대 건수 (0=전체)")
        parser.add_argument("--maxchars", type=int, default=6000, help="raw_text 최대 길이")

    def handle(self, *args, **o):
        qs = Document.objects.all()
        if o["source"]:
            qs = qs.filter(source__name__icontains=o["source"])
        if o["only_empty"]:
            qs = qs.filter(summary="")
        if o["ids"]:
            ids = [int(x) for x in o["ids"].split(",") if x.strip().isdigit()]
            qs = qs.filter(id__in=ids)
        qs = qs.order_by("-id")
        if o["limit"]:
            qs = qs[:o["limit"]]
        for d in qs:
            rec = {
                "id": d.id,
                "title": d.title,
                "url": d.url,
                "authors": d.authors,
                "published_date": str(d.published_date) if d.published_date else "",
                "raw_text": (d.raw_text or "")[:o["maxchars"]],
            }
            self.stdout.write(json.dumps(rec, ensure_ascii=False))
