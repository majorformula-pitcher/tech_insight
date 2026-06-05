"""
정보과학회지 PDF를 읽어 Document 테이블에 적재하는 명령.

폴더 구조 가정:
    data_source/<출처이름>/<YY>_<M>/<논문제목>.pdf
    예) data_source/정보과학회지/23_1/사이버 위협 동향 분석.pdf

사용 예:
    python manage.py import_journal                # 정보과학회지 전체
    python manage.py import_journal --limit 5      # 앞 5개만 (테스트)
    python manage.py import_journal --no-text      # 본문 추출 생략(메타만 빠르게)
    python manage.py import_journal --reextract    # 이미 적재된 문서의 본문을 새 로직으로 다시 추출
"""
import re
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from insight.models import Source, Document
from insight.pipeline.pdf_extract import extract_pdf

# data_source 폴더 (이 파일 기준 ../../../../data_source)
DATA_ROOT = Path(__file__).resolve().parents[4] / "data_source"

# 행정성 문서 — 분석 대상에서 제외 (제목에 아래 표현이 포함되면 스킵)
ADMIN_PATTERNS = [
    "월별 특집계획", "학회동정", "월별 학술행사", "학술행사 개최계획",
    "특집원고 모집", "목차", "학회지를 맡으면서", "취임사",
    "특집을 내면서", "편집위원", "을 내면서",
]


def is_admin_doc(title: str) -> bool:
    return any(p in title for p in ADMIN_PATTERNS)


def parse_ym(folder_name: str):
    """'23_1' -> date(2023, 1, 1). 실패 시 None."""
    m = re.match(r"^(\d{2})_(\d{1,2})$", folder_name)
    if not m:
        return None
    yy, mm = int(m.group(1)), int(m.group(2))
    return date(2000 + yy, mm, 1)


# 본문 추출은 2단 편집을 고려하는 pipeline.pdf_extract.extract_pdf 사용
extract_text = extract_pdf


class Command(BaseCommand):
    help = "정보과학회지 PDF를 DB에 적재한다."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="정보과학회지",
                            help="data_source 하위 폴더명 (기본: 정보과학회지)")
        parser.add_argument("--limit", type=int, default=0,
                            help="처리할 최대 문서 수 (0=전체)")
        parser.add_argument("--no-text", action="store_true",
                            help="본문 텍스트 추출을 생략 (메타데이터만)")
        parser.add_argument("--reextract", action="store_true",
                            help="이미 적재된 문서의 본문을 새 추출 로직으로 다시 채운다")

    def handle(self, *args, **opts):
        source_name = opts["source"]
        limit = opts["limit"]
        extract = not opts["no_text"]

        src_dir = DATA_ROOT / source_name
        if not src_dir.is_dir():
            self.stderr.write(self.style.ERROR(f"폴더 없음: {src_dir}"))
            return

        if opts["reextract"]:
            return self._reextract(source_name, limit)

        source, created = Source.objects.get_or_create(
            name=source_name,
            defaults={"type": Source.Type.PAPER},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"출처 생성: {source_name}"))

        # 월 폴더를 시간순으로 정렬
        month_dirs = sorted(
            (d for d in src_dir.iterdir() if d.is_dir() and parse_ym(d.name)),
            key=lambda d: parse_ym(d.name),
        )

        n_added, n_skip_admin, n_skip_dup, n_err, n_total = 0, 0, 0, 0, 0
        for mdir in month_dirs:
            pub = parse_ym(mdir.name)
            for pdf in sorted(mdir.glob("*.pdf")):
                title = pdf.stem
                if is_admin_doc(title):
                    n_skip_admin += 1
                    continue
                if limit and n_added >= limit:
                    self._summary(n_added, n_skip_admin, n_skip_dup, n_err)
                    return

                rel_path = str(pdf.relative_to(DATA_ROOT))
                if Document.objects.filter(source=source, file_path=rel_path).exists():
                    n_skip_dup += 1
                    continue

                n_total += 1
                raw = ""
                if extract:
                    try:
                        raw = extract_text(pdf)
                    except Exception as e:  # noqa: BLE001
                        n_err += 1
                        self.stderr.write(self.style.WARNING(f"추출 실패: {title} :: {e}"))

                Document.objects.create(
                    source=source,
                    title=title,
                    published_date=pub,
                    raw_text=raw,
                    file_path=rel_path,
                    status=Document.Status.EXTRACTED if raw else Document.Status.COLLECTED,
                )
                n_added += 1
                if n_added % 20 == 0:
                    self.stdout.write(f"  ...{n_added}편 적재")

        self._summary(n_added, n_skip_admin, n_skip_dup, n_err)

    def _reextract(self, source_name, limit):
        """이미 DB에 있는 문서의 raw_text를 새 추출 로직으로 다시 채운다."""
        qs = Document.objects.filter(source__name=source_name).order_by("published_date")
        if limit:
            qs = qs[:limit]
        n_ok, n_err, n_skip = 0, 0, 0
        total = qs.count()
        self.stdout.write(f"재추출 대상: {total}편")
        for doc in qs:
            pdf = DATA_ROOT / doc.file_path
            if not pdf.is_file():
                n_skip += 1
                self.stderr.write(self.style.WARNING(f"파일 없음: {doc.file_path}"))
                continue
            try:
                raw = extract_text(pdf)
            except Exception as e:  # noqa: BLE001
                n_err += 1
                self.stderr.write(self.style.WARNING(f"추출 실패: {doc.title} :: {e}"))
                continue
            doc.raw_text = raw
            doc.status = Document.Status.EXTRACTED if raw else Document.Status.COLLECTED
            doc.save(update_fields=["raw_text", "status"])
            n_ok += 1
            if n_ok % 20 == 0:
                self.stdout.write(f"  ...{n_ok}/{total}편 재추출")
        self.stdout.write(self.style.SUCCESS(
            f"\n[재추출 완료] 성공 {n_ok}편 / 파일없음 {n_skip} / 오류 {n_err}"
        ))

    def _summary(self, added, admin, dup, err):
        self.stdout.write(self.style.SUCCESS(
            f"\n[완료] 적재 {added}편 / 행정성 제외 {admin} / 중복 스킵 {dup} / 추출오류 {err}"
        ))
