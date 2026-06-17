"""
Supabase 'ai-bongchae' 테이블 → Document(뉴스) 자동 동기화.

엑셀 수동 import(import_news_excel)를 대체한다. URL 로 중복 판정.
하루 1회 스케줄러(작업 스케줄러/cron)로 실행하는 것을 전제로 한다.
요약(summary)은 이미 AI로 작성돼 있으므로 재요약 없이 그대로 저장한다.

환경변수: SUPABASE_URL, SUPABASE_KEY (또는 SUPABASE_ANON_KEY)

사용 예:
    python manage.py collect_news_supabase            # 전체 동기화
    python manage.py collect_news_supabase --days 3   # 최근 3일분만 (일일 실행용)
    python manage.py collect_news_supabase --dry-run  # 저장 없이 미리보기
"""
from datetime import date, timedelta
from urllib.parse import urlparse

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from insight.collectors.supabase_news import fetch_news
from insight.models import Source, Document


def media_from_url(url):
    """URL 도메인에서 매체명 추출 (www 제거). 예: aitimes.com"""
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host
    except Exception:  # noqa: BLE001
        return ""


class Command(BaseCommand):
    help = "Supabase ai-bongchae 테이블의 뉴스를 Document(뉴스)로 동기화한다."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=0,
                            help="최근 N일(created_at 기준)만 가져옴 (0=전체)")
        parser.add_argument("--limit", type=int, default=0,
                            help="최대 행 수 (0=무제한)")
        parser.add_argument("--dry-run", action="store_true",
                            help="저장하지 않고 파싱 결과만 미리보기")

    def handle(self, *args, **opts):
        since = None
        if opts["days"] > 0:
            since = (date.today() - timedelta(days=opts["days"])).isoformat()

        try:
            rows = fetch_news(limit=opts["limit"], since=since)
        except Exception as e:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"Supabase 조회 실패: {e}"))
            return

        dry = opts["dry_run"]
        source, _ = Source.objects.get_or_create(
            name="뉴스", defaults={"type": Source.Type.NEWS})

        n_new = n_dup = n_skip = 0
        for row in rows:
            url = (row.get("url") or "").strip()
            title = (row.get("title") or "").strip()
            summary = (row.get("summary") or "").strip()
            if not url or not title:
                n_skip += 1
                continue
            if Document.objects.filter(url=url).exists():
                n_dup += 1
                continue

            cdt = parse_datetime(row.get("created_at") or "")          # 등록 시각(aware)
            pdt = parse_datetime(row.get("published_at") or "")        # 발행 시각
            pub = (pdt or cdt)
            pub = pub.date() if pub else None

            if dry:
                if n_new < 3:
                    self.stdout.write(
                        f"[{row.get('category')}] {title[:40]} | {url[:40]} | {cdt}")
                n_new += 1
                continue

            doc = Document.objects.create(
                source=source,
                title=title[:500],
                authors=media_from_url(url),
                published_date=pub,
                raw_text=summary,
                summary=summary,
                category=(row.get("category") or "기타").strip(),
                engine=(row.get("engine") or "").strip(),
                image=(row.get("image") or "").strip()[:1000],
                url=url,
                status=Document.Status.ANALYZED,
            )
            # created_at 은 auto_now_add 라 create 시 무시됨 → update 로 등록시각 반영
            if cdt:
                Document.objects.filter(pk=doc.pk).update(created_at=cdt)
            n_new += 1

        verb = "미리보기" if dry else "저장"
        self.stdout.write(self.style.SUCCESS(
            f"\n[Supabase 뉴스 {verb} 완료] 신규 {n_new} / 중복 {n_dup} / 건너뜀 {n_skip}"))
