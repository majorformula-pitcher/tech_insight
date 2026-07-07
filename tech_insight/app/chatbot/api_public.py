"""조회 전용 공개 API (읽기 전용) — 부서 내 활용/분석용.

인증: 헤더 Authorization: Bearer <token>  (settings.API_TOKENS, 쉼표구분)
저작권: 원문 전문(raw_text)은 절대 노출하지 않는다. 요약 + 메타데이터 + 원문 링크만.
embedding: 분석용. base64(float32)로 직렬화 → 소비자는
    np.frombuffer(base64.b64decode(x), dtype=np.float32)  로 복원(1024차원, bge-m3).

엔드포인트(모두 GET):
    /api/v1/search?q=&type=&category=&from=&to=&source_name=&limit=&include_embedding=
    /api/v1/documents/<id>?include_embedding=
    /api/v1/embeddings?type=&category=            # 전체 벡터 일괄(NDJSON 스트림)
    /api/v1/meta                                  # 필터 값·형식 안내
"""
import base64
import json
from functools import wraps

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET

from insight.categories import CATEGORIES
from insight.models import Document, Source
from insight.retriever import retrieve

# 출처유형 코드 매핑
_STMAP = {"paper": Source.Type.PAPER, "blog": Source.Type.BLOG, "news": Source.Type.NEWS}
_ALL_TYPES = [Source.Type.PAPER, Source.Type.BLOG, Source.Type.NEWS]
# 브라우즈(빈 쿼리) 시 노출할 공개 필드 — 원문 전문 제외
_BROWSE_VALS = ("id", "title", "summary", "authors", "affiliations",
                "published_date", "url", "category", "source__type", "source__name")
_TRUE = {"1", "true", "yes", "on"}


# ── 인증 ────────────────────────────────────────────────
def _token_ok(request) -> bool:
    tok = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    valid = [t.strip() for t in (getattr(settings, "API_TOKENS", "") or "").split(",") if t.strip()]
    return bool(tok) and tok in valid


def api_auth(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not _token_ok(request):
            return JsonResponse({"error": "unauthorized"}, status=401)
        return view(request, *args, **kwargs)
    return wrapped


# ── 헬퍼 ────────────────────────────────────────────────
def _emb_b64(raw):
    """float32 이진 blob → base64 문자열 (없으면 None)."""
    return base64.b64encode(raw).decode("ascii") if raw else None


def _shape(d: dict) -> dict:
    """.values() dict → 공개 응답 형태(원문 전문 제외)."""
    return {
        "id": d["id"], "title": d["title"], "summary": d["summary"],
        "authors": d["authors"], "affiliations": d["affiliations"],
        "published_date": d["published_date"], "url": d.get("url", ""),
        "category": d.get("category", ""),
        "source_type": d.get("source__type", ""),
        "source_name": d.get("source__name", ""),
    }


def _types_of(request):
    """type= 파라미터 → 검색 대상 출처유형 리스트(없으면 전체)."""
    t = (request.GET.get("type") or "").strip().lower()
    return [_STMAP[t]] if t in _STMAP else list(_ALL_TYPES)


def _filters_of(request):
    """공통 하드 필터(category, 날짜범위, source_name) 추출."""
    g = request.GET
    f = {}
    if g.get("category"):
        f["category"] = g["category"].strip()
    df, dt = (g.get("date_from") or g.get("from")), (g.get("date_to") or g.get("to"))
    if df and dt:
        f["date_from"], f["date_to"] = df.strip(), dt.strip()
    if g.get("source_name"):
        f["source_name"] = g["source_name"].strip()
    return f


def _enrich(results, include_emb):
    """결과에 category(retrieve 결과엔 없음)와 embedding(옵션)을 한 번의 조회로 붙인다."""
    if not results:
        return results
    need_cat = any("category" not in r for r in results)
    if not (need_cat or include_emb):
        return results
    vals = ["id"]
    if need_cat:
        vals.append("category")
    if include_emb:
        vals += ["embedding", "embed_model"]
    meta = {m["id"]: m for m in Document.objects.filter(
        id__in=[r["id"] for r in results]).values(*vals)}
    for r in results:
        m = meta.get(r["id"], {})
        if need_cat:
            r["category"] = m.get("category", "")
        if include_emb:
            r["embedding"] = _emb_b64(m.get("embedding"))
            r["embed_model"] = m.get("embed_model", "")
    return results


def _browse(types, f, limit):
    """빈 쿼리(주제 없음) → 필터 조건으로 최신순 목록."""
    qs = Document.objects.filter(source__type__in=types).exclude(summary="")
    if f.get("category"):
        qs = qs.filter(category__iexact=f["category"])
    if f.get("date_from") and f.get("date_to"):
        qs = qs.filter(published_date__range=(f["date_from"], f["date_to"]))
    if f.get("source_name"):
        s = f["source_name"]
        qs = qs.filter(Q(source__name__icontains=s) | Q(authors__icontains=s))
    qs = qs.order_by("-published_date", "-created_at")[:limit]
    return [_shape(d) for d in qs.values(*_BROWSE_VALS)]


# ── 엔드포인트 ────────────────────────────────────────────
@require_GET
@api_auth
def search(request):
    """의미검색(q 있으면 벡터+키워드) 또는 필터 브라우즈(q 없으면 최신순)."""
    q = (request.GET.get("q") or "").strip()
    try:
        limit = max(1, min(int(request.GET.get("limit") or 10), 50))
    except ValueError:
        limit = 10
    include_emb = (request.GET.get("include_embedding") or "").lower() in _TRUE
    types = _types_of(request)
    f = _filters_of(request)

    if q:
        results = retrieve(q, top_k=limit, source_type=types, filters=f)
    else:
        results = _browse(types, f, limit)

    _enrich(results, include_emb)
    return JsonResponse({"count": len(results), "results": results})


@require_GET
@api_auth
def document(request, doc_id):
    """단건 상세(요약+메타+링크). include_embedding=true 면 벡터 포함."""
    include_emb = (request.GET.get("include_embedding") or "").lower() in _TRUE
    vals = list(_BROWSE_VALS) + (["embedding", "embed_model"] if include_emb else [])
    d = Document.objects.filter(id=doc_id).values(*vals).first()
    if not d:
        return JsonResponse({"error": "not found"}, status=404)
    out = _shape(d)
    if include_emb:
        out["embedding"] = _emb_b64(d.get("embedding"))
        out["embed_model"] = d.get("embed_model", "")
    return JsonResponse(out)


@require_GET
@api_auth
def embeddings(request):
    """분석용 전체 벡터 일괄 내보내기 (NDJSON 스트림). 원문 전문 미포함."""
    types = _types_of(request)
    category = (request.GET.get("category") or "").strip()
    qs = (Document.objects.filter(source__type__in=types)
          .exclude(embedding__isnull=True)
          .exclude(summary=""))
    if category:
        qs = qs.filter(category__iexact=category)
    qs = qs.values("id", "embedding", "embed_model", "title", "category",
                   "source__type", "published_date", "url").order_by("id")

    def gen():
        for d in qs.iterator(chunk_size=200):
            pd = d["published_date"]
            yield json.dumps({
                "id": d["id"],
                "embedding": _emb_b64(d["embedding"]),
                "embed_model": d.get("embed_model", ""),
                "title": d["title"],
                "category": d.get("category", ""),
                "source_type": d.get("source__type", ""),
                "published_date": pd.isoformat() if pd else None,
                "url": d.get("url", ""),
            }, ensure_ascii=False) + "\n"

    resp = StreamingHttpResponse(gen(), content_type="application/x-ndjson")
    resp["Cache-Control"] = "no-cache"
    resp["Content-Disposition"] = 'attachment; filename="embeddings.ndjson"'
    return resp


@require_GET
@api_auth
def meta(request):
    """필터 가능한 값·임베딩 형식 안내(소비자 디스커버리용)."""
    return JsonResponse({
        "categories": list(CATEGORIES),
        "source_types": ["paper", "blog", "news"],
        "total_documents": Document.objects.exclude(summary="").count(),
        "embed_model": "ollama:bge-m3",
        "embedding_dim": 1024,
        "embedding_format": "base64-float32",
    })
