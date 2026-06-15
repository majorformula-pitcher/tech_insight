"""
저명한 논문 수집 명령 (하이브리드).

두 가지 '저명도' 신호를 함께 수집한다:
  - scholar: Semantic Scholar 인용수 상위 (검증된 권위 논문)
  - hf     : Hugging Face 추천수 상위 (요즘 화제의 최신 논문)

각 논문의 영어 초록을 EXAONE로 한국어 요약해 Document(type=paper)로 저장하므로
한국어 검색기·챗봇 근거 풀에 그대로 합류한다. 중복은 url 로 판정한다.

사용 예:
    python manage.py collect_papers                       # 둘 다, 분야당 8건 + 화제 15건
    python manage.py collect_papers --sources scholar     # 인용수만
    python manage.py collect_papers --sources hf          # 화제만
    python manage.py collect_papers --limit 5             # scholar 분야당 5건
    python manage.py collect_papers --since-year 2024 --min-citations 100
    python manage.py collect_papers --no-summary          # 요약 생략
"""
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from insight.collectors.semantic_scholar import TOPICS, fetch_top_cited
from insight.collectors.hf_papers import fetch_trending
from insight.collectors.arxiv import arxiv_id_from_url, download_pdf
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
    help = "Semantic Scholar(인용수)·HF Papers(추천수) 기반 저명 논문을 수집·요약·저장한다."

    def add_arguments(self, parser):
        parser.add_argument("--sources", type=str, default="scholar,hf",
                            help="수집 소스: scholar,hf (콤마 구분, 기본 둘 다)")
        parser.add_argument("--limit", type=int, default=8,
                            help="scholar 분야당 / hf 전체 최대 논문 수 (기본 8)")
        parser.add_argument("--since-year", type=int, default=2023,
                            help="scholar: 이 연도 이후 논문만 (기본 2023)")
        parser.add_argument("--min-citations", type=int, default=50,
                            help="scholar: 최소 인용수 (기본 50)")
        parser.add_argument("--min-upvotes", type=int, default=10,
                            help="hf: 최소 추천수 (기본 10)")
        parser.add_argument("--days", type=int, default=1,
                            help="hf: 최근 며칠치를 모을지 (기본 1=최신만, 예: 7=1주일)")
        parser.add_argument("--hf-limit", type=int, default=20,
                            help="hf: 이번 실행에서 가져올 최대 화제 논문 수 (기본 20)")
        parser.add_argument("--max", type=int, default=0,
                            help="이번 실행 전체 최대 신규 건수 (0=무제한)")
        parser.add_argument("--no-summary", action="store_true",
                            help="EXAONE 한국어 요약 생략 (초록 원문만 저장)")
        parser.add_argument("--no-pdf", action="store_true",
                            help="arXiv PDF 다운로드 생략 (DB 메타·요약만 저장)")

    def handle(self, *args, **opts):
        sources = [s.strip() for s in opts["sources"].split(",") if s.strip()]
        do_summary = not opts["no_summary"]
        hard_max = opts["max"]
        self._do_summary = do_summary
        self._do_pdf = not opts["no_pdf"]
        self._hard_max = hard_max
        self._n_new = 0
        self._stats = {"dup": 0, "skip": 0, "err": 0}

        if "scholar" in sources:
            src, _ = Source.objects.get_or_create(
                name="Semantic Scholar",
                defaults={"type": Source.Type.PAPER, "url": "https://www.semanticscholar.org"},
            )
            for code, ko, query in TOPICS:
                if self._maxed():
                    break
                self.stdout.write(f"[Scholar · {ko}({code})] 인용수 상위 수집 중...")
                try:
                    items = fetch_top_cited(
                        query, limit=opts["limit"],
                        since_year=opts["since_year"], min_citations=opts["min_citations"],
                    )
                except Exception as e:  # noqa: BLE001
                    self.stderr.write(self.style.WARNING(f"  조회 실패 {code}: {e}"))
                    continue
                self._ingest(items, src)
                time.sleep(2)  # API 예의

        if "hf" in sources and not self._maxed():
            src, _ = Source.objects.get_or_create(
                name="HF Papers",
                defaults={"type": Source.Type.PAPER, "url": "https://huggingface.co/papers"},
            )
            self.stdout.write(
                f"[HF Papers] 추천수 상위 수집 중... (최근 {opts['days']}일, "
                f"추천 {opts['min_upvotes']}+ , 최대 {opts['hf_limit']}편)")
            try:
                items = fetch_trending(limit=opts["hf_limit"],
                                       min_upvotes=opts["min_upvotes"],
                                       days=opts["days"])
                self._ingest(items, src)
            except Exception as e:  # noqa: BLE001
                self.stderr.write(self.style.WARNING(f"  조회 실패 HF: {e}"))

        s = self._stats
        self.stdout.write(self.style.SUCCESS(
            f"\n[저명 논문 수집 완료] 신규 {self._n_new} / 중복 {s['dup']} / "
            f"초록부족 {s['skip']} / 요약오류 {s['err']}"
        ))

    def _maxed(self) -> bool:
        return bool(self._hard_max) and self._n_new >= self._hard_max

    def _ingest(self, items, source):
        """수집 항목들을 요약·저장."""
        for it in items:
            if self._maxed():
                break
            if Document.objects.filter(url=it["url"]).exists():
                self._stats["dup"] += 1
                continue
            abstract = it["abstract"]
            if not abstract or len(abstract) < 40:
                self._stats["skip"] += 1
                continue

            # arXiv PDF 다운로드 (data_source/<소스>/<연도>/<id 제목>.pdf)
            file_path = ""
            if self._do_pdf:
                file_path = self._save_pdf(it, source.name)

            summary = ""
            if self._do_summary:
                try:
                    summary = chat(
                        SUMMARY_SYSTEM,
                        f"제목: {it['title']}\n\n초록(English):\n{abstract[:4000]}",
                        max_tokens=600,
                    ).strip()
                except Exception as e:  # noqa: BLE001
                    self._stats["err"] += 1
                    self.stderr.write(self.style.WARNING(
                        f"  요약 실패: {it['title'][:30]} :: {e}"))

            Document.objects.create(
                source=source,
                title=it["title"][:500],
                authors=it["authors"],
                affiliations="",
                published_date=it["published_date"],
                raw_text=abstract,
                summary=summary,
                url=it["url"],
                file_path=file_path,
                category="",
                metric=it.get("metric", ""),
                status=(Document.Status.ANALYZED if summary
                        else Document.Status.EXTRACTED),
            )
            self._n_new += 1
            pdf_tag = " 📄" if file_path else ""
            self.stdout.write(f"  + [{it.get('metric','')}] {it['title'][:46]}{pdf_tag}")

    def _save_pdf(self, it, source_name) -> str:
        """논문 PDF를 data_source 아래에 저장하고 상대경로(file_path)를 반환."""
        arxiv_id = arxiv_id_from_url(it.get("url", ""))
        if not arxiv_id:
            return ""
        year = (it.get("published_date") or "")[:4] or "기타"
        dest_dir = os.path.join(str(DATA_DIR), source_name, year)
        try:
            path = download_pdf(arxiv_id, dest_dir, it.get("title", ""))
            time.sleep(1.5)  # arXiv 다운로드 예의
        except Exception as e:  # noqa: BLE001
            self.stderr.write(self.style.WARNING(f"  PDF 실패: {arxiv_id} :: {e}"))
            return ""
        if not path:
            return ""
        return os.path.relpath(path, str(DATA_DIR))
