"""논문·블로그의 빈 category 를 LLM으로 채운다(6종 분류).

뉴스는 수집 시 category가 채워지지만 논문/블로그는 비어 있어, 카테고리 필터가
그들을 놓치는 문제를 해결한다(QUERY_PIPELINE_설계.md §9-D).

분류 체계: AI / Robot / Security / Data / IT / 기타  (뉴스와 동일 taxonomy)
속도를 위해 한 번의 LLM 호출로 여러 건을 분류(배치). 정렬·검증 후 저장.

사용:
    python manage.py backfill_categories                 # 빈 category 전부
    python manage.py backfill_categories --max 30        # 30건만(검증용)
    python manage.py backfill_categories --batch 12      # 배치 크기
    python manage.py backfill_categories --refresh       # 이미 채워진 것도 재분류
    python manage.py backfill_categories --types paper   # 논문만
"""
import json
import re

from django.core.management.base import BaseCommand

from insight.llm import chat, current_model
from insight.models import Document, Source

CATS = ["AI", "Robot", "Security", "Data", "IT", "기타"]
_CATSET = set(CATS)

_SYS = (
    "너는 기술 문서 분류기다. 각 문서를 다음 6개 중 정확히 하나로 분류한다: "
    "AI(인공지능·머신러닝·LLM·컴퓨터비전·음성), "
    "Robot(로봇·휴머노이드·자율주행·제어), "
    "Security(보안·암호·해킹·프라이버시), "
    "Data(데이터베이스·빅데이터·데이터엔지니어링·분석 인프라), "
    "IT(반도체·클라우드·네트워크·SW개발·기업/서비스 일반), "
    "기타(위에 안 맞음). "
    "입력은 번호가 매겨진 문서 목록이다. "
    'JSON 객체 하나만 출력한다(설명 금지). 형식: {"1":"AI","2":"Robot",...} '
    "모든 번호에 대해 반드시 값을 준다."
)


def _classify_batch(items):
    """items: [(idx, title, summary)] → {idx: category}. 실패분은 '기타'."""
    lines = []
    for i, title, summary in items:
        snip = (summary or "").replace("\n", " ")[:200]
        lines.append(f"{i}. 제목: {title[:120]} / 요약: {snip}")
    prompt = "다음 문서들을 분류하라:\n" + "\n".join(lines)
    out = {}
    try:
        raw = chat(_SYS, prompt, max_tokens=400)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        for k, v in data.items():
            if isinstance(v, str) and v.strip() in _CATSET:
                try:
                    out[int(k)] = v.strip()
                except (ValueError, TypeError):
                    pass
    except Exception:  # noqa: BLE001  배치 실패 → 호출측에서 '기타' 처리
        pass
    return out


class Command(BaseCommand):
    help = "논문·블로그의 빈 category를 LLM으로 6종 분류해 채운다."

    def add_arguments(self, parser):
        parser.add_argument("--max", type=int, default=0, help="최대 처리 건수(0=전체)")
        parser.add_argument("--batch", type=int, default=10, help="LLM 1회 분류 건수")
        parser.add_argument("--refresh", action="store_true", help="이미 채워진 것도 재분류")
        parser.add_argument("--types", default="paper,blog", help="대상 유형(쉼표): paper,blog,news")

    def handle(self, *args, **opts):
        tmap = {"paper": Source.Type.PAPER, "blog": Source.Type.BLOG, "news": Source.Type.NEWS}
        types = [tmap[t.strip()] for t in opts["types"].split(",") if t.strip() in tmap]

        qs = Document.objects.filter(source__type__in=types).exclude(summary="")
        if not opts["refresh"]:
            qs = qs.filter(category="")
        qs = qs.order_by("id")
        if opts["max"] > 0:
            qs = qs[:opts["max"]]

        rows = list(qs.values_list("id", "title", "summary"))
        total = len(rows)
        self.stdout.write(f"분류 대상: {total}건 (모델 {current_model()}, 배치 {opts['batch']})")
        if not total:
            self.stdout.write(self.style.SUCCESS("채울 문서가 없습니다."))
            return

        batch = opts["batch"]
        done = 0
        dist = {c: 0 for c in CATS}
        for start in range(0, total, batch):
            chunk = rows[start:start + batch]
            items = [(i + 1, r[1], r[2]) for i, r in enumerate(chunk)]  # 배치내 1-기반 번호
            result = _classify_batch(items)
            for i, r in enumerate(chunk):
                cat = result.get(i + 1, "기타")
                if cat not in _CATSET:
                    cat = "기타"
                Document.objects.filter(pk=r[0]).update(category=cat)
                dist[cat] += 1
                done += 1
            self.stdout.write(f"  ...{done}/{total}")

        self.stdout.write(self.style.SUCCESS(f"\n[category 백필 완료] {done}건"))
        self.stdout.write("분포: " + ", ".join(f"{c}={dist[c]}" for c in CATS))
