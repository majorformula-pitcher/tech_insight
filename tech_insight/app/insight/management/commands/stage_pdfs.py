"""
'AI 요약이 있는(또는 본문이 있는) 문서'의 원본 PDF만 media 폴더로 복사한다.
이렇게 모은 media 폴더만 서버에 올리면, 행정성 문서를 뺀 실제 논문 PDF만
다운로드 가능해진다.

전제: data_source 의 원본 PDF가 로컬에 있어야 한다(=이 명령은 보통 로컬에서 실행).

사용 예:
    # 요약(summary)이 있는 문서의 PDF만 media 로 복사
    python manage.py stage_pdfs

    # 본문이라도 있는 문서까지 포함
    python manage.py stage_pdfs --include-extracted

    # 실제 복사 없이 어떤 게 대상인지만 출력
    python manage.py stage_pdfs --dry-run
"""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from insight.models import Document

# data_source 폴더 (이 파일 기준)
DATA_ROOT = Path(__file__).resolve().parents[4] / "data_source"


class Command(BaseCommand):
    help = "요약/본문이 있는 문서의 원본 PDF만 media 폴더로 복사한다."

    def add_arguments(self, parser):
        parser.add_argument("--include-extracted", action="store_true",
                            help="요약이 없어도 본문(raw_text)이 있으면 포함")
        parser.add_argument("--dry-run", action="store_true",
                            help="복사하지 않고 대상만 출력")

    def handle(self, *args, **opts):
        from django.db.models import Q
        qs = Document.objects.exclude(file_path="")
        if opts["include_extracted"]:
            # 요약이 있거나 본문이 있는 문서
            target = qs.filter(~Q(summary="") | ~Q(raw_text=""))
        else:
            # 요약이 있는 문서만
            target = qs.exclude(summary="")

        media_root = Path(settings.MEDIA_ROOT)
        n_ok, n_missing, n_skip = 0, 0, 0
        total = target.count()
        self.stdout.write(f"대상 문서: {total}편 (PDF 복사 위치: {media_root})")

        for doc in target:
            src = DATA_ROOT / doc.file_path
            if not src.is_file():
                n_missing += 1
                self.stderr.write(self.style.WARNING(f"원본 없음: {doc.file_path}"))
                continue
            dst = media_root / doc.file_path
            if opts["dry_run"]:
                self.stdout.write(f"  [dry] {doc.file_path}")
                n_ok += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n_ok += 1
            if n_ok % 20 == 0:
                self.stdout.write(f"  ...{n_ok}/{total} 복사")

        self.stdout.write(self.style.SUCCESS(
            f"\n[PDF 스테이징 완료] 복사 {n_ok} / 원본없음 {n_missing} / 스킵 {n_skip}"
        ))
        if not opts["dry_run"]:
            self.stdout.write(
                "이제 media 폴더를 서버로 올리세요 (예: scp -r media ubuntu@서버IP:~/tech_insight/tech_insight/app/)"
            )
