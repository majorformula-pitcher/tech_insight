"""
분석 챗봇 — 뉴스/질문을 받아 관련 논문 요약을 근거로 LLM이 분석 답변.
RAG: retrieve(관련문서) → 프롬프트 구성 → llm.chat() → 답변 + 출처.
"""
import json

from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from insight.llm import chat, stream, current_provider
from insight.retriever import retrieve

SYSTEM_PROMPT = (
    "너는 한국 기술 트렌드 분석가다. 한국어로만 답한다. "
    "반드시 아래 제공된 근거 자료에 기반해 분석하라. "
    "'근거 논문'은 검증된 핵심 근거로, '참고 최신 뉴스'는 최신 동향 보조자료로 활용하되 "
    "논문 근거를 우선한다. 근거에 없는 내용은 추측하지 말고, 자료가 부족하면 그렇다고 밝혀라. "
    "답변은 ①핵심 분석 ②파급효과 ③근거가 된 자료 흐름 순으로 간결하게."
)


@ensure_csrf_cookie
def index(request):
    """챗봇 페이지. ?news=<id> 가 있으면 해당 뉴스를 미리 질문칸에 채운다."""
    from insight.models import Document, Source
    prefill = ""
    news_id = request.GET.get("news")
    if news_id:
        d = Document.objects.filter(id=news_id, source__name="뉴스").first()
        if d:
            body = d.summary or d.raw_text[:500]
            prefill = f"[뉴스] {d.title}\n{body}\n\n이 뉴스의 파급효과를 우리 논문 근거로 분석해줘."
    # 근거로 쓰는 자료 수 — retriever와 동일 기준(요약 있음)
    paper_count = (Document.objects
                   .filter(source__type=Source.Type.PAPER)
                   .exclude(summary="").count())
    news_count = (Document.objects
                  .filter(source__type=Source.Type.NEWS)
                  .exclude(summary="").count())
    return render(request, "chatbot/index.html", {
        "provider": current_provider(), "prefill": prefill,
        "paper_count": paper_count, "news_count": news_count,
    })


@ensure_csrf_cookie
def news(request):
    """뉴스 카드 목록 페이지 (카테고리 필터·검색)."""
    from insight.models import Document

    qs = Document.objects.filter(source__name="뉴스").exclude(summary="")
    category = request.GET.get("cat", "").strip()
    query = request.GET.get("q", "").strip()
    if category and category != "All":
        qs = qs.filter(category=category)
    if query:
        qs = qs.filter(title__icontains=query)
    qs = qs.order_by("-published_date", "-created_at")[:2000]

    items = [{
        "id": d.id,
        "title": d.title,
        "summary_lines": [s for s in d.summary.split("\n") if s.strip()],
        "category": d.category or "기타",
        "image": d.image,
        "source": d.authors,
        "url": d.url,
        "date": (f"{d.published_date.year}. {d.published_date.month}. {d.published_date.day}."
                 if d.published_date else ""),
        "engine": d.engine,
        "created_at": timezone.localtime(d.created_at).strftime("%Y.%m.%d %H:%M"),
    } for d in qs]

    # 카테고리별 개수
    cats = ["All", "AI", "Robot", "Security", "Data", "IT", "기타"]
    return render(request, "chatbot/news.html", {
        "items": items, "cats": cats,
        "active_cat": category or "All", "query": query,
        "total": len(items),
    })


def _build_prompt(question, history=None):
    """질문으로 논문(검증 근거)+뉴스(최신 동향) 검색 후 프롬프트 구성.
    (docs, news, user_prompt) 반환."""
    docs = retrieve(question, top_k=8)                          # 논문 8편 (핵심 근거)
    news = retrieve(question, top_k=6, source_type="news")      # 뉴스 후보
    # 분석 중인 뉴스 자신이 근거로 딸려오는 자기참조 제거 후 4건만
    news = [n for n in news if n["title"][:25] not in question][:4]

    if docs:
        context = "\n\n".join(
            f"[논문 {i+1}] {d['title']} ({d['published_date']}, {d['affiliations']})\n요약: {d['summary']}"
            for i, d in enumerate(docs)
        )
    else:
        context = "(관련 논문을 찾지 못함)"

    news_ctx = "\n\n".join(
        f"[뉴스 {i+1}] {d['title']} ({d['published_date']}, {d['authors']})\n요약: {d['summary']}"
        for i, d in enumerate(news)
    )

    convo = ""
    if history:
        # 직전 대화 몇 턴을 맥락으로 (후속 질문 이어가기용)
        turns = []
        for h in history[-4:]:
            role = "사용자" if h.get("role") == "user" else "분석가"
            turns.append(f"{role}: {h.get('content', '').strip()}")
        if turns:
            convo = "# 이전 대화\n" + "\n".join(turns) + "\n\n"

    user_prompt = (
        f"# 근거 논문 요약 (검증된 핵심 근거)\n{context}\n\n"
        + (f"# 참고 최신 뉴스 (동향 보조자료)\n{news_ctx}\n\n" if news_ctx else "")
        + f"{convo}"
        + f"# 질문/뉴스\n{question}\n\n"
        + "위 근거에 기반해 분석하라. 논문을 핵심 근거로, 뉴스는 최신 동향 참고로 활용하라."
    )
    return docs, news, user_prompt


def _sources_of(docs, news=None):
    """근거 자료 목록(논문+뉴스)을 프론트 표시용으로 직렬화. 종류(kind) 라벨 포함."""
    out = [
        {
            "title": d["title"],
            "published_date": str(d["published_date"]),
            "meta": d["affiliations"],
            "kind": "논문",
            "score": d["score"],
        }
        for d in docs
    ]
    out += [
        {
            "title": d["title"],
            "published_date": str(d["published_date"]),
            "meta": d["authors"],
            "kind": "뉴스",
            "score": d["score"],
        }
        for d in (news or [])
    ]
    return out


@require_POST
def ask(request):
    """질문 처리(비스트리밍): 검색 → LLM → JSON. (호환용)"""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "잘못된 요청"}, status=400)
    question = (payload.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "질문을 입력하세요."}, status=400)
    docs, news, user_prompt = _build_prompt(question, payload.get("history"))
    try:
        answer = chat(SYSTEM_PROMPT, user_prompt, max_tokens=2000)
    except Exception as e:  # noqa: BLE001
        return JsonResponse({"error": f"LLM 호출 실패: {e}"}, status=502)
    return JsonResponse({
        "answer": answer,
        "sources": _sources_of(docs, news),
        "provider": current_provider(),
    })


@require_POST
def ask_stream(request):
    """질문 처리(스트리밍): 토큰을 SSE로 흘려보낸다."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "잘못된 요청"}, status=400)
    question = (payload.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "질문을 입력하세요."}, status=400)

    docs, news, user_prompt = _build_prompt(question, payload.get("history"))

    def event_stream():
        # 먼저 근거 출처를 한 번 보냄
        yield "event: sources\ndata: " + json.dumps(_sources_of(docs, news), ensure_ascii=False) + "\n\n"
        # 그다음 답변 토큰을 흘려보냄
        try:
            for piece in stream(SYSTEM_PROMPT, user_prompt, max_tokens=2000):
                yield "event: token\ndata: " + json.dumps({"t": piece}, ensure_ascii=False) + "\n\n"
        except Exception as e:  # noqa: BLE001
            yield "event: error\ndata: " + json.dumps({"error": str(e)}, ensure_ascii=False) + "\n\n"
        yield "event: done\ndata: {}\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"  # nginx 버퍼링 방지
    return resp
