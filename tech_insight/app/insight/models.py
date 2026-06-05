"""
Tech Insight 플랫폼 데이터 모델.

설계 문서(tech_insight/ARCHITECTURE.md) 4번 항목 기반.
1단계(데이터 DB화)에서는 메타데이터 + 본문 텍스트 저장에 집중하고,
임베딩/벡터(embedding_id 등)는 필드만 마련해 두고 2단계에서 채운다.
"""
from django.db import models


class Source(models.Model):
    """데이터 출처. 예: 정보과학회지, OpenAI Blog, arXiv cs.AI."""

    class Type(models.TextChoices):
        PAPER = "paper", "논문/학회지"
        BLOG = "blog", "블로그"
        NEWS = "news", "뉴스"

    name = models.CharField("이름", max_length=200, unique=True)
    type = models.CharField("유형", max_length=10, choices=Type.choices, default=Type.PAPER)
    url = models.URLField("사이트 URL", blank=True)
    rss_url = models.URLField("RSS 주소", blank=True, help_text="자동 수집용 (4단계)")
    is_active = models.BooleanField("수집 활성화", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "출처"
        verbose_name_plural = "출처"

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class Keyword(models.Model):
    """기술 키워드. 대시보드의 라이프사이클 분류와 연결."""

    class Lifecycle(models.TextChoices):
        GROWTH = "성장", "성장"
        NEW = "신규", "신규"
        DECLINE = "쇠퇴", "쇠퇴"
        VOLATILE = "변동", "변동"
        STABLE = "정체", "정체"

    name = models.CharField("키워드", max_length=100, unique=True)
    category = models.CharField("분류", max_length=100, blank=True)
    lifecycle = models.CharField(
        "라이프사이클", max_length=10, choices=Lifecycle.choices, blank=True
    )

    class Meta:
        verbose_name = "키워드"
        verbose_name_plural = "키워드"

    def __str__(self):
        return self.name


class Document(models.Model):
    """수집한 문서 1건 (논문/블로그 글/뉴스). 핵심 테이블."""

    class Status(models.TextChoices):
        COLLECTED = "collected", "수집됨"
        EXTRACTED = "extracted", "본문추출됨"
        EMBEDDED = "embedded", "임베딩됨"
        ANALYZED = "analyzed", "분석완료"

    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="documents", verbose_name="출처"
    )
    title = models.CharField("제목", max_length=500)
    authors = models.CharField("저자", max_length=500, blank=True, help_text="쉼표 구분")
    affiliations = models.CharField("소속", max_length=500, blank=True, help_text="쉼표 구분")
    published_date = models.DateField("발행일", null=True, blank=True)

    raw_text = models.TextField("본문 원문", blank=True)
    summary = models.TextField("AI 요약", blank=True)

    url = models.URLField("원본 URL", blank=True, max_length=1000)
    file_path = models.CharField("로컬 파일 경로", max_length=1000, blank=True)

    status = models.CharField(
        "상태", max_length=12, choices=Status.choices, default=Status.COLLECTED
    )
    keywords = models.ManyToManyField(
        Keyword, related_name="documents", blank=True, verbose_name="키워드"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "문서"
        verbose_name_plural = "문서"
        ordering = ["-published_date", "-created_at"]
        # 같은 출처에 같은 파일이 중복 적재되는 것 방지
        constraints = [
            models.UniqueConstraint(
                fields=["source", "file_path"],
                name="uniq_source_filepath",
                condition=~models.Q(file_path=""),
            )
        ]

    def __str__(self):
        return self.title[:60]


class Chunk(models.Model):
    """본문을 검색 단위로 자른 조각 (RAG 검색의 최소 단위). 2단계에서 본격 사용."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="chunks", verbose_name="문서"
    )
    order = models.PositiveIntegerField("순번", default=0)
    text = models.TextField("조각 본문")
    # 2단계: 벡터 DB(Chroma/pgvector) 내 ID를 여기에 연결
    embedding_id = models.CharField("벡터 ID", max_length=100, blank=True)

    class Meta:
        verbose_name = "본문조각"
        verbose_name_plural = "본문조각"
        ordering = ["document", "order"]

    def __str__(self):
        return f"{self.document_id}#{self.order}"
