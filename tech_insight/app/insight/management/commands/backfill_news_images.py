"""
뉴스 카드 썸네일 백필 — 이미지가 없는 뉴스 Document의 URL에서 og:image를 받아 채운다.

엑셀 임포트 뉴스처럼 image가 비어있는 경우, 원문 URL을 크롤링해 대표 이미지를 넣는다.
본문은 건드리지 않고 image 필드만 갱신한다. 차단/실패한 URL은 건너뛴다.

사용 예:
    python manage.py backfill_news_images               # 이미지 없는 뉴스 전체
    python manage.py backfill_news_images --max 50       # 최대 50건만
    python manage.py backfill_news_images --sleep 1.0    # 요청 간 간격(초)
"""
import time

from django.core.management.base import BaseCommand

from insight.collectors.news import fetch_og_image
from insight.models import Document


class Command(BaseCommand):
    help = "이미지 없는 뉴스의 원문 URL에서 og:image를 받아 썸네일을 채운다."

    def add_arguments(self, parser):
        parser.add_argument("--max", type=int, default=0,
                            help="이번 실행 최대 처리 건수 (0=전체)")
        parser.add_argument("--sleep", type=float, default=0.6,
                            help="요청 사이 간격(초), 기본 0.6")

    def handle(self, *args, **opts):
        hard_max = opts["max"]
        pause = opts["sleep"]

        qs = (Document.objects
              .filter(source__name="뉴스", image="")
              .exclude(url="")
              .order_by("-published_date"))
        total = qs.count()
        self.stdout.write(f"이미지 없는 뉴스: {total}건 처리 시작...")

        n_ok = n_fail = 0
        for i, doc in enumerate(qs.iterator(), 1):
            if hard_max and (n_ok + n_fail) >= hard_max:
                break
            img = fetch_og_image(doc.url)
            if img:
                Document.objects.filter(pk=doc.pk).update(image=img[:1000])
                n_ok += 1
                mark = "OK "
            else:
                n_fail += 1
                mark = "-- "
            if i % 20 == 0 or img:
                self.stdout.write(f"  [{mark}] ({n_ok}장) {doc.title[:38]}")
            time.sleep(pause)

        self.stdout.write(self.style.SUCCESS(
            f"\n[썸네일 백필 완료] 성공 {n_ok} / 실패(이미지없음·차단) {n_fail}"))
