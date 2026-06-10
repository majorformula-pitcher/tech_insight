"""
뉴스 RSS 자동 수집 명령.

흐름: RSS 피드 → 신규 기사 → 본문 크롤링 → EXAONE 요약 → Document 저장.
중복은 url 로 판정한다.

사용 예:
    python manage.py collect_news                  # 전체 피드, 피드당 5건
    python manage.py collect_news --limit 3        # 피드당 3건
    python manage.py collect_news --no-summary     # 요약 생략(빠른 수집)
    python manage.py collect_news --max 10         # 이번 실행 최대 10건만
"""
from django.core.management.base import BaseCommand

from insight.collectors.news import RSS_FEEDS, fetch_feed, extract_body
from insight.llm import chat
from insight.models import Source, Document

SUMMARY_SYSTEM = (
    "너는 뉴스 요약 전문가다. 한국어로만, 핵심만 4문장으로 요약한다. "
    "각 문장은 '~입니다/~했습니다' 평어체로 끝내고, 숫자·불릿 기호는 붙이지 마라. "
    "구체적 수치·고유명사·핵심 결과를 포함하라."
)


class Command(BaseCommand):
    help = "뉴스 RSS를 수집해 본문 크롤링·요약 후 Document에 저장한다."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=5,
                            help="피드당 최대 기사 수 (기본 5)")
        parser.add_argument("--max", type=int, default=0,
                            help="이번 실행 전체 최대 신규 건수 (0=무제한)")
        parser.add_argument("--no-summary", action="store_true",
                            help="EXAONE 요약 생략 (본문만 저장)")

    def handle(self, *args, **opts):
        per_feed = opts["limit"]
        hard_max = opts["max"]
        do_summary = not opts["no_summary"]

        source, _ = Source.objects.get_or_create(
            name="뉴스", defaults={"type": Source.Type.NEWS}
        )

        n_new, n_dup, n_skip, n_err = 0, 0, 0, 0
        for name, url in RSS_FEEDS:
            if hard_max and n_new >= hard_max:
                break
            self.stdout.write(f"[{name}] 수집 중...")
            for item in fetch_feed(name, url, limit=per_feed):
                if hard_max and n_new >= hard_max:
                    break
                # 중복 (url 기준)
                if Document.objects.filter(url=item["url"]).exists():
                    n_dup += 1
                    continue
                # 본문 크롤링
                body = extract_body(item["url"])
                if not body or len(body) < 80:
                    # 본문 못 가져오면 RSS 요약이라도
                    body = item.get("rss_summary", "")
                    if not body:
                        n_skip += 1
                        continue

                summary = ""
                if do_summary:
                    try:
                        summary = chat(
                            SUMMARY_SYSTEM,
                            f"제목: {item['title']}\n\n본문:\n{body[:4000]}",
                            max_tokens=400,
                        )
                    except Exception as e:  # noqa: BLE001
                        n_err += 1
                        self.stderr.write(self.style.WARNING(f"요약 실패: {item['title'][:30]} :: {e}"))

                Document.objects.create(
                    source=source,
                    title=item["title"][:500],
                    published_date=item["published_date"],
                    raw_text=body,
                    summary=summary,
                    url=item["url"],
                    authors=item["source_name"],   # 출처 매체명을 저자 칸에 기록
                    status=(Document.Status.ANALYZED if summary
                            else Document.Status.EXTRACTED),
                )
                n_new += 1
                self.stdout.write(f"  + {item['title'][:45]}")

        self.stdout.write(self.style.SUCCESS(
            f"\n[뉴스 수집 완료] 신규 {n_new} / 중복 {n_dup} / 본문없음 {n_skip} / 요약오류 {n_err}"
        ))
