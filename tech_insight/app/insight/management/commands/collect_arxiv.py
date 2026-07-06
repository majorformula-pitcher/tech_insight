"""
arXiv 논문 자동 수집 명령.

흐름: arXiv API(분야별) → 신규 논문 → EXAONE로 한국어 요약 → Document 저장.
영어 초록을 한국어로 요약해 저장하므로 한국어 검색기(retriever)와 호환된다.
중복은 url(arXiv abs URL) 로 판정한다.

사용 예:
    python manage.py collect_arxiv                     # 전체 분야, 분야당 15건
    python manage.py collect_arxiv --limit 5           # 분야당 5건
    python manage.py collect_arxiv --cats cs.AI,cs.CL  # 특정 분야만
    python manage.py collect_arxiv --max 10            # 이번 실행 최대 10건
    python manage.py collect_arxiv --no-summary        # 요약 생략(초록 원문만 저장)
"""
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from insight.classify import classify_category
from insight.collectors.arxiv import ARXIV_CATEGORIES, fetch_category, download_pdf
from insight.llm import chat
from insight.models import Source, Document

DATA_DIR = settings.BASE_DIR.parent / "data_source"

SUMMARY_SYSTEM = (
    "너는 해외 AI/컴퓨터과학 논문을 한국어로 요약하는 전문가다. 한국어로만 답한다. "
    "주어진 영어 초록을 읽고 핵심 기여·방법·결과를 4~5문장으로 요약하라. "
    "각 문장은 '~한다/~했다/~이다' 평서체로, 불릿·번호·머리말 없이 문장만 출력한다. "
    "전문 용어는 한국어로 옮기되 필요하면 괄호로 원어를 병기한다."
)


class Command(BaseCommand):
    help = "arXiv 분야별 최신 논문을 수집해 한국어 요약 후 Document에 저장한다."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=15,
                            help="분야당 최대 논문 수 (기본 15)")
        parser.add_argument("--max", type=int, default=0,
                            help="이번 실행 전체 최대 신규 건수 (0=무제한)")
        parser.add_argument("--cats", type=str, default="",
                            help="수집 분야 콤마 구분 (예: cs.AI,cs.CL). 기본: 전체")
        parser.add_argument("--no-summary", action="store_true",
                            help="EXAONE 한국어 요약 생략 (초록 원문만 저장)")
        parser.add_argument("--no-pdf", action="store_true",
                            help="arXiv PDF 다운로드 생략 (DB 메타·요약만 저장)")

    def handle(self, *args, **opts):
        per_cat = opts["limit"]
        hard_max = opts["max"]
        do_summary = not opts["no_summary"]
        do_pdf = not opts["no_pdf"]
        if opts["cats"].strip():
            cats = [c.strip() for c in opts["cats"].split(",") if c.strip()]
        else:
            cats = [c for c, _ in ARXIV_CATEGORIES]

        source, _ = Source.objects.get_or_create(
            name="arXiv",
            defaults={"type": Source.Type.PAPER, "url": "https://arxiv.org"},
        )

        n_new, n_dup, n_skip, n_err = 0, 0, 0, 0
        for ci, cat in enumerate(cats):
            if hard_max and n_new >= hard_max:
                break
            self.stdout.write(f"[{cat}] 수집 중...")
            try:
                items = fetch_category(cat, per_cat)
            except Exception as e:  # noqa: BLE001
                self.stderr.write(self.style.WARNING(f"  조회 실패 {cat}: {e}"))
                continue

            for it in items:
                if hard_max and n_new >= hard_max:
                    break
                # 중복 (url 기준)
                if Document.objects.filter(url=it["url"]).exists():
                    n_dup += 1
                    continue
                abstract = it["abstract"]
                if not abstract or len(abstract) < 40:
                    n_skip += 1
                    continue

                # PDF 다운로드 (data_source/arXiv/<연도>/<id 제목>.pdf)
                file_path = ""
                if do_pdf:
                    year = (it.get("published_date") or "")[:4] or "기타"
                    dest_dir = os.path.join(str(DATA_DIR), source.name, year)
                    try:
                        path = download_pdf(it["arxiv_id"], dest_dir, it["title"])
                        time.sleep(1.5)  # arXiv 다운로드 예의
                        if path:
                            file_path = os.path.relpath(path, str(DATA_DIR))
                    except Exception as e:  # noqa: BLE001
                        self.stderr.write(self.style.WARNING(
                            f"  PDF 실패: {it['arxiv_id']} :: {e}"))

                summary = ""
                if do_summary:
                    try:
                        summary = chat(
                            SUMMARY_SYSTEM,
                            f"제목: {it['title']}\n\n초록(English):\n{abstract[:4000]}",
                            max_tokens=600,
                        ).strip()
                    except Exception as e:  # noqa: BLE001
                        n_err += 1
                        self.stderr.write(self.style.WARNING(
                            f"  요약 실패: {it['title'][:30]} :: {e}"))

                # 수집 시 카테고리 자동 분류(요약/초록 기반). 분류 실패는 '기타'로 폴백.
                category = (classify_category(it["title"], summary or abstract)
                           if do_summary else "")

                Document.objects.create(
                    source=source,
                    title=it["title"][:500],
                    authors=it["authors"],
                    affiliations="",   # arXiv 메타에 소속이 일관되지 않아 비움
                    published_date=it["published_date"],
                    raw_text=abstract,         # 영어 초록 원문 보관
                    summary=summary,           # 한국어 요약 (검색·표시용)
                    url=it["url"],
                    file_path=file_path,
                    category=category,
                    status=(Document.Status.ANALYZED if summary
                            else Document.Status.EXTRACTED),
                )
                n_new += 1
                pdf_tag = " 📄" if file_path else ""
                self.stdout.write(f"  + {it['title'][:50]}{pdf_tag}")

            # arXiv API 예의: 분야 사이 간격
            if ci < len(cats) - 1:
                time.sleep(3)

        self.stdout.write(self.style.SUCCESS(
            f"\n[arXiv 수집 완료] 신규 {n_new} / 중복 {n_dup} / "
            f"초록부족 {n_skip} / 요약오류 {n_err}"
        ))
