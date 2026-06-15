"""
문서 임베딩 생성 — 의미 기반 검색용 벡터를 만들어 저장한다.

대상: 요약(summary)이 있는 모든 Document(논문+뉴스).
증분: 아직 임베딩이 없거나, 다른 모델로 만든 것만 처리한다(멱등).
      → 새 논문을 수집한 뒤 다시 실행하면 추가분만 임베딩한다.

사용 예:
    python manage.py embed_documents              # 임베딩 없는 문서만
    python manage.py embed_documents --batch 32   # 배치 크기
    python manage.py embed_documents --refresh    # 전부 다시 임베딩(모델 교체 시)
    python manage.py embed_documents --max 100    # 최대 100건만
"""
import numpy as np
from django.core.management.base import BaseCommand
from django.db.models import Q

from insight.embeddings import embed_texts, current_model
from insight.models import Document


def embed_text_of(doc) -> str:
    """임베딩 입력 텍스트: 제목 + 요약."""
    return f"{doc.title}\n{doc.summary}".strip()


class Command(BaseCommand):
    help = "요약이 있는 문서를 임베딩해 의미 검색용 벡터를 저장한다(증분)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=16, help="임베딩 배치 크기")
        parser.add_argument("--max", type=int, default=0, help="이번 실행 최대 처리 건수(0=전체)")
        parser.add_argument("--refresh", action="store_true",
                            help="이미 임베딩된 것도 전부 다시 생성(모델 교체 시)")

    def handle(self, *args, **opts):
        model = current_model()
        batch_size = opts["batch"]
        hard_max = opts["max"]

        qs = Document.objects.exclude(summary="")
        if not opts["refresh"]:
            # 임베딩이 없거나 다른 모델로 만든 것만
            qs = qs.filter(Q(embedding__isnull=True) | ~Q(embed_model=model))
        qs = qs.order_by("id")
        total = qs.count()
        self.stdout.write(f"임베딩 대상: {total}건 (모델 {model})")
        if not total:
            self.stdout.write(self.style.SUCCESS("새로 임베딩할 문서가 없습니다."))
            return

        done = 0
        batch = []
        for doc in qs.iterator():
            batch.append(doc)
            if len(batch) >= batch_size:
                done += self._flush(batch, model)
                batch = []
                self.stdout.write(f"  ...{done}/{total}")
                if hard_max and done >= hard_max:
                    break
        if batch and not (hard_max and done >= hard_max):
            done += self._flush(batch, model)

        self.stdout.write(self.style.SUCCESS(f"\n[임베딩 완료] {done}건 처리"))

    def _flush(self, batch, model) -> int:
        texts = [embed_text_of(d) for d in batch]
        try:
            vecs = embed_texts(texts)
        except Exception as e:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"임베딩 실패: {e}"))
            return 0
        for d, v in zip(batch, vecs):
            d.embedding = np.asarray(v, dtype=np.float32).tobytes()
            d.embed_model = model
        Document.objects.bulk_update(batch, ["embedding", "embed_model"])
        return len(batch)
