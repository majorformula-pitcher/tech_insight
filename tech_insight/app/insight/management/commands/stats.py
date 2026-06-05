"""적재된 데이터 현황을 요약 출력한다.  사용: python manage.py stats"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from insight.models import Source, Document


class Command(BaseCommand):
    help = "DB에 적재된 문서 현황 요약."

    def handle(self, *args, **opts):
        total = Document.objects.count()
        self.stdout.write(f"총 문서: {total}편\n")

        self.stdout.write("[출처별]")
        for s in Source.objects.annotate(n=Count("documents")):
            self.stdout.write(f"  - {s.name}: {s.n}편")

        self.stdout.write("\n[상태별]")
        for row in Document.objects.values("status").annotate(n=Count("id")).order_by("-n"):
            self.stdout.write(f"  - {row['status']}: {row['n']}편")

        self.stdout.write("\n[연도별]")
        years = {}
        for d in Document.objects.exclude(published_date=None).values_list("published_date", flat=True):
            years[d.year] = years.get(d.year, 0) + 1
        for y in sorted(years):
            self.stdout.write(f"  - {y}: {years[y]}편")

        # 본문 추출 품질 점검
        empty = Document.objects.filter(raw_text="").count()
        self.stdout.write(f"\n본문 비어있는 문서: {empty}편")
