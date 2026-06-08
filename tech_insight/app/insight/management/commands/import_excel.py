"""
Claude Cowork가 추출한 엑셀(.xlsx)을 읽어 Document 테이블에 적재한다.

엑셀 컬럼(첫 행 헤더, 영문):
    title, authors, affiliations, published_date, raw_text, summary, file_path
(file_path 는 없어도 됨 — 없으면 title 로 중복 판정)

사용 예:
    # 기존 정보과학회지 문서를 모두 지우고 엑셀로 새로 채움
    python manage.py import_excel ../tech_insight_documents.xlsx --replace

    # 기존은 두고 추가/갱신만 (file_path 또는 title 기준 upsert)
    python manage.py import_excel ../tech_insight_documents.xlsx

    # 출처 이름 지정 (기본: 정보과학회지)
    python manage.py import_excel data.xlsx --source 정보과학회지 --replace
"""
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from insight.models import Source, Document

# 엑셀 헤더 ↔ 모델 필드. 한글 헤더로 와도 받아주도록 별칭도 둔다.
HEADER_ALIASES = {
    "title": "title", "제목": "title",
    "authors": "authors", "저자": "authors",
    "affiliations": "affiliations", "소속": "affiliations",
    "published_date": "published_date", "발행일": "published_date", "발행연월": "published_date",
    "raw_text": "raw_text", "본문": "raw_text", "본문원문": "raw_text",
    "summary": "summary", "요약": "summary", "ai요약": "summary",
    "file_path": "file_path", "파일경로": "file_path", "경로": "file_path",
}


def parse_date(value):
    """엑셀 셀(문자열/날짜)을 date로. 실패하면 None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y_%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class Command(BaseCommand):
    help = "Cowork가 만든 엑셀(.xlsx)을 읽어 Document 에 적재한다."

    def add_arguments(self, parser):
        parser.add_argument("excel_path", help="엑셀 파일 경로(.xlsx)")
        parser.add_argument("--source", default="정보과학회지",
                            help="출처 이름 (기본: 정보과학회지)")
        parser.add_argument("--replace", action="store_true",
                            help="해당 출처의 기존 문서를 모두 삭제하고 새로 적재")
        parser.add_argument("--sheet", default=None,
                            help="읽을 시트 이름 (기본: 첫 시트)")

    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("openpyxl 이 필요합니다: pip install openpyxl")

        path = Path(opts["excel_path"]).expanduser()
        if not path.is_file():
            raise CommandError(f"엑셀 파일 없음: {path}")

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[opts["sheet"]] if opts["sheet"] else wb.active

        rows = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows)
        except StopIteration:
            raise CommandError("엑셀이 비어 있습니다.")

        # 헤더 → 필드 매핑 (대소문자/공백 무시)
        col_field = {}
        for idx, name in enumerate(header_row):
            if name is None:
                continue
            key = str(name).strip().lower()
            field = HEADER_ALIASES.get(key)
            if field:
                col_field[idx] = field
        if "title" not in col_field.values():
            raise CommandError(
                f"필수 컬럼 'title' 을 찾지 못했습니다. 발견된 헤더: {header_row}"
            )

        source, _ = Source.objects.get_or_create(
            name=opts["source"], defaults={"type": Source.Type.PAPER}
        )

        if opts["replace"]:
            n_del, _ = Document.objects.filter(source=source).delete()
            self.stdout.write(self.style.WARNING(f"[replace] 기존 문서 삭제: {n_del}건"))

        n_new, n_upd, n_skip = 0, 0, 0
        for row in rows:
            data = {}
            for idx, field in col_field.items():
                val = row[idx] if idx < len(row) else None
                data[field] = "" if val is None else str(val).strip()

            title = data.get("title", "").strip()
            if not title:
                n_skip += 1
                continue

            published = parse_date(data.get("published_date"))
            file_path = data.get("file_path", "").strip()
            raw_text = data.get("raw_text", "")

            fields = {
                "authors": data.get("authors", ""),
                "affiliations": data.get("affiliations", ""),
                "published_date": published,
                "raw_text": raw_text,
                "summary": data.get("summary", ""),
                "file_path": file_path,
                "status": (
                    Document.Status.ANALYZED if data.get("summary")
                    else (Document.Status.EXTRACTED if raw_text else Document.Status.COLLECTED)
                ),
            }

            # 중복 판정: file_path 우선, 없으면 title
            lookup = ({"source": source, "file_path": file_path}
                      if file_path else {"source": source, "title": title})
            obj = Document.objects.filter(**lookup).first()
            if obj:
                for k, v in {**fields, "title": title}.items():
                    setattr(obj, k, v)
                obj.save()
                n_upd += 1
            else:
                Document.objects.create(source=source, title=title, **fields)
                n_new += 1

        wb.close()
        self.stdout.write(self.style.SUCCESS(
            f"\n[엑셀 적재 완료] 신규 {n_new} / 갱신 {n_upd} / 건너뜀 {n_skip}"
        ))
