"""
해외 연구소 블로그 수집 명령 (Anthropic / OpenAI / DeepMind 등).

흐름: 블로그(RSS/크롤링) → 신규 글 → 본문 크롤링 → EXAONE 한국어 요약 → Document 저장.
연구소 블로그는 '근거 풀'(type=blog, 논문과 동급)로 저장되어 챗봇 분석 근거로 쓰인다.
중복은 url 로 판정한다.

사용 예:
    python manage.py collect_blogs                  # 전체 블로그, 소스당 8건
    python manage.py collect_blogs --limit 5        # 소스당 5건
    python manage.py collect_blogs --max 20         # 이번 실행 최대 20건
    python manage.py collect_blogs --no-summary     # 요약 생략(본문만)
"""
from django.core.management.base import BaseCommand

from insight.collectors.blogs import fetch_all_blogs
from insight.collectors.news import extract_article
from insight.llm import chat
from insight.models import Source, Document

SUMMARY_SYSTEM = (
    "너는 해외 AI 연구소 블로그 글을 한국어로 요약하는 전문가다. 한국어로만 답한다. "
    "주어진 영어 본문을 읽고 핵심 발표·기여·시사점을 4~5문장으로 요약하라. "
    "각 문장은 '~한다/~했다/~이다' 평서체로, 불릿·번호·머리말 없이 문장만 출력한다. "
    "전문 용어는 한국어로 옮기되 필요하면 괄호로 원어를 병기한다."
)


class Command(BaseCommand):
    help = "해외 연구소 블로그(Anthropic/OpenAI/DeepMind 등)를 수집·요약·저장한다."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=8,
                            help="블로그 소스당 최대 글 수 (기본 8, 0=무제한·피드 전체)")
        parser.add_argument("--max", type=int, default=0,
                            help="이번 실행 전체 최대 신규 건수 (0=무제한)")
        parser.add_argument("--no-summary", action="store_true",
                            help="EXAONE 한국어 요약 생략 (본문만 저장)")
        parser.add_argument("--only", default="",
                            help="특정 출처만 수집 (부분일치, 예: Anthropic)")

    def handle(self, *args, **opts):
        per = opts["limit"]
        hard_max = opts["max"]
        do_summary = not opts["no_summary"]

        n_new = n_dup = n_skip = n_err = 0
        for name, items in fetch_all_blogs(per, only=opts["only"]):
            if hard_max and n_new >= hard_max:
                break
            source, _ = Source.objects.get_or_create(
                name=name, defaults={"type": Source.Type.BLOG, "url": ""})
            self.stdout.write(f"[{name}] {len(items)}건 확인...")
            for it in items:
                if hard_max and n_new >= hard_max:
                    break
                url = it["url"]
                if Document.objects.filter(url=url).exists():
                    n_dup += 1
                    continue
                art = extract_article(url)
                body, image = art["body"], art["image"]
                if not body or len(body) < 120:
                    body = it.get("rss_summary", "")
                    if not body or len(body) < 120:
                        n_skip += 1
                        continue

                title = (it.get("title") or "").strip() or (art.get("title") or "").strip()
                summary = ""
                if do_summary:
                    try:
                        summary = chat(
                            SUMMARY_SYSTEM,
                            f"제목: {title}\n\n본문(English):\n{body[:4000]}",
                            max_tokens=600,
                        ).strip()
                    except Exception as e:  # noqa: BLE001
                        n_err += 1
                        self.stderr.write(self.style.WARNING(
                            f"  요약 실패: {title[:30]} :: {e}"))

                Document.objects.create(
                    source=source,
                    title=(title or "(제목 없음)")[:500],
                    authors=name,                # 연구소명
                    published_date=it.get("published_date"),
                    raw_text=body,
                    summary=summary,
                    image=image[:1000] if image else "",
                    url=url,
                    engine="EXAONE",
                    status=(Document.Status.ANALYZED if summary
                            else Document.Status.EXTRACTED),
                )
                n_new += 1
                self.stdout.write(f"  + {title[:50]}")

        self.stdout.write(self.style.SUCCESS(
            f"\n[블로그 수집 완료] 신규 {n_new} / 중복 {n_dup} / "
            f"본문부족 {n_skip} / 요약오류 {n_err}"))
