"""
분석 챗봇 — 뉴스/질문을 받아 관련 논문 요약을 근거로 LLM이 분석 답변.
RAG: retrieve(관련문서) → 프롬프트 구성 → llm.chat() → 답변 + 출처.
"""
import json

from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from insight.llm import chat, stream, current_provider
from insight.retriever import retrieve

SYSTEM_PROMPT = (
    "너는 한국 기술 트렌드 분석가다. 한국어로만 답한다. "
    "반드시 아래 제공된 '근거 논문 요약'에 기반해 분석하라. "
    "근거에 없는 내용은 추측하지 말고, 자료가 부족하면 그렇다고 밝혀라. "
    "답변은 ①핵심 분석 ②파급효과 ③근거가 된 논문 흐름 순으로 간결하게."
)


@ensure_csrf_cookie
def index(request):
    """챗봇 페이지. ?news=<id> 가 있으면 해당 뉴스를 미리 질문칸에 채운다."""
    prefill = ""
    news_id = request.GET.get("news")
    if news_id:
        from insight.models import Document
        d = Document.objects.filter(id=news_id, source__name="뉴스").first()
        if d:
            body = d.summary or d.raw_text[:500]
            prefill = f"[뉴스] {d.title}\n{body}\n\n이 뉴스의 파급효과를 우리 논문 근거로 분석해줘."
    return render(request, "chatbot/index.html", {
        "provider": current_provider(), "prefill": prefill,
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
    qs = qs.order_by("-published_date", "-created_at")[:60]

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
    } for d in qs]

    # 카테고리별 개수
    cats = ["All", "AI", "Robot", "Security", "Data", "IT", "기타"]
    return render(request, "chatbot/news.html", {
        "items": items, "cats": cats,
        "active_cat": category or "All", "query": query,
        "total": len(items),
    })


def _build_prompt(question, history=None):
    """질문(+이전 대화)으로 관련 문서 검색 + 프롬프트 구성. (docs, user_prompt) 반환."""
    docs = retrieve(question, top_k=5)
    if docs:
        context = "\n\n".join(
            f"[논문 {i+1}] {d['title']} ({d['published_date']}, {d['affiliations']})\n요약: {d['summary']}"
            for i, d in enumerate(docs)
        )
    else:
        context = "(관련 논문을 찾지 못함)"

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
        f"# 근거 논문 요약\n{context}\n\n"
        f"{convo}"
        f"# 질문/뉴스\n{question}\n\n"
        f"위 근거에 기반해 분석하라."
    )
    return docs, user_prompt


def _sources_of(docs):
    return [
        {
            "title": d["title"],
            "published_date": str(d["published_date"]),
            "authors": d["authors"],
            "affiliations": d["affiliations"],
            "score": d["score"],
        }
        for d in docs
    ]


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
    docs, user_prompt = _build_prompt(question, payload.get("history"))
    try:
        answer = chat(SYSTEM_PROMPT, user_prompt, max_tokens=700)
    except Exception as e:  # noqa: BLE001
        return JsonResponse({"error": f"LLM 호출 실패: {e}"}, status=502)
    return JsonResponse({
        "answer": answer,
        "sources": _sources_of(docs),
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

    docs, user_prompt = _build_prompt(question, payload.get("history"))

    def event_stream():
        # 먼저 근거 출처를 한 번 보냄
        yield "event: sources\ndata: " + json.dumps(_sources_of(docs), ensure_ascii=False) + "\n\n"
        # 그다음 답변 토큰을 흘려보냄
        try:
            for piece in stream(SYSTEM_PROMPT, user_prompt, max_tokens=700):
                yield "event: token\ndata: " + json.dumps({"t": piece}, ensure_ascii=False) + "\n\n"
        except Exception as e:  # noqa: BLE001
            yield "event: error\ndata: " + json.dumps({"error": str(e)}, ensure_ascii=False) + "\n\n"
        yield "event: done\ndata: {}\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"  # nginx 버퍼링 방지
    return resp
