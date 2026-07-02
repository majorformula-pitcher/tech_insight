"""
분석 챗봇 — 뉴스/질문을 받아 관련 논문 요약을 근거로 LLM이 분석 답변.
RAG: retrieve(관련문서) → 프롬프트 구성 → llm.chat() → 답변 + 출처.
"""
import json
import re

from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_GET

from insight.llm import (chat, stream, current_provider, current_model,
                         set_ollama_model, list_ollama_models)
from insight.retriever import retrieve, _tokens

# 분석형 프롬프트 — '분석/전망/영향' 등 해석을 요청한 질문에 사용
ANALYSIS_PROMPT = (
    "너는 한국 기술 트렌드 분석가다. 한국어로만 답한다. "
    "먼저 질문(또는 뉴스)의 핵심 주제·대상을 정확히 파악하고, 분석은 반드시 그 주제에 직접 연결하라. "
    "아래 제공된 근거 자료에만 기반하라. "
    "'근거 논문'은 검증된 핵심 근거로, '참고 최신 뉴스'는 최신 동향 보조자료로 활용하되 논문 근거를 우선한다. "
    "중요: 제공된 근거가 질문 주제와 직접 관련이 적으면, 억지로 끼워 맞추지 마라. "
    "그럴 때는 '이 주제에 직접 관련된 자료가 부족하다'고 먼저 분명히 밝히고, "
    "관련 있는 자료만 골라 제한적으로만 분석하라. 주제와 무관한 자료로 일반론을 채우지 마라. "
    "근거에 없는 내용은 추측하지 마라. "
    "인용 규칙(반드시 지킬 것): 모든 핵심 주장·문장 끝에 그 근거가 된 자료의 실제 번호를 "
    "대괄호로 표기하라(예: ...두께가 줄어든다[논문 1][뉴스 3]). "
    "각 자료 블록 앞에 붙은 번호(1,2,3…)를 그대로 쓰되, 'N'이나 'X' 같은 문자를 그대로 적지 말고 "
    "반드시 해당 자료의 실제 숫자로 바꿔 써라. 근거를 특정할 수 없는 문장은 쓰지 마라. "
    "답변은 ①핵심 분석 ②파급효과 ③근거가 된 자료 흐름 세 부분으로 구성하라. "
    "①핵심 분석과 ②파급효과는 각각 3가지 이상의 관점(기술·산업·시장·사회 등)으로 나누어, "
    "각 항목을 근거와 함께 충분히 상세하고 구체적으로 서술하라(다만 근거에 없는 추측·과장은 금지)."
)

# 조회형 프롬프트 — '보여줘/알려줘/목록' 등 단순 조회 질문에 사용.
# 의도적으로 '분석/파급효과'를 지시하지 않고, 오히려 금지한다(작은 모델이 끌려가지 않도록).
LOOKUP_PROMPT = (
    "너는 한국 기술 자료 안내자다. 한국어로만 답한다. "
    "제공된 근거 자료에만 기반하고 추측하지 마라. 사용자가 자료 조회를 요청했다. "
    "[형식 규칙 — 반드시 지킬 것] "
    "분류 제목은 '## 논문 자료', '## 뉴스 자료'로 쓴다. "
    "각 자료는 한 줄로, 정확히 이 형식으로만 쓴다: "
    "`- **제목 (YYYY-MM-DD)** — 한 문장 요약`. "
    "'제목:', '날짜:', '핵심요지:', '요약:' 같은 라벨을 줄마다 붙이지 말고, "
    "한 자료를 여러 줄(불릿)로 쪼개지 마라. 한 자료 = 한 불릿이다. "
    "논문을 먼저, 뉴스를 뒤에 둔다. "
    "분석·파급효과·시사점·결론·총평 문장은 절대 쓰지 마라. 자료 나열로만 답한다. "
    "[예시]\n"
    "## 논문 자료\n"
    "- **Introducing Anthropic's Transparency Hub (2025-02-27)** — 투명성 허브를 출범해 모델 평가·안전 테스트 방법론을 공개했다.\n"
    "- **Anthropic signs CMS health tech pledge (2025-07-30)** — CMS와 헬스케어 데이터 공유 현대화를 위한 서약을 체결했다.\n"
    "## 뉴스 자료\n"
    "- **크라우드웍스, 피지컬AI 데이터랩 신설 (2026-05-29)** — 휴머노이드 로봇 데이터 수집·구축을 강화한다."
)

# 하위호환: 외부에서 SYSTEM_PROMPT 를 참조할 수 있으므로 기본값을 유지
SYSTEM_PROMPT = ANALYSIS_PROMPT

# 분석을 요청하는 신호 단어 — 있으면 분석, 없으면 단순 조회로 본다(조회 쪽으로 보수적)
_ANALYSIS_KEYWORDS = (
    "분석", "전망", "영향", "시사", "파급", "효과", "평가", "비교",
    "예측", "함의", "인사이트", "의미", "왜", "해석", "정리해서 분석",
)


def _is_analysis(question: str) -> bool:
    """질문이 해석/분석을 요구하는지 판단. 신호 단어가 없으면 단순 조회로 본다."""
    return any(k in (question or "") for k in _ANALYSIS_KEYWORDS)


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
            prefill = f"[뉴스] {d.title}\n{body}\n\n이 뉴스의 파급효과를 우리 논문과 뉴스를 근거로 분석해줘."
    # 근거 자료 수 — 대시보드·관리화면 총계와 일치하도록 출처 유형별 전체 건수로 표시
    paper_count = (Document.objects
                   .filter(source__type__in=[Source.Type.PAPER, Source.Type.BLOG])
                   .count())
    news_count = (Document.objects
                  .filter(source__type=Source.Type.NEWS)
                  .count())
    return render(request, "chatbot/index.html", {
        "provider": current_provider(), "model": current_model(), "prefill": prefill,
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
    # 요약/등록 시각(created_at) 내림차순 — 카드에 표시되는 시각과 정렬 순서를 일치시킨다.
    qs = qs.order_by("-created_at", "-id")[:2000]

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


def _drop_weak(items, ratio=0.45, keep_min=3):
    """상위 점수 대비 너무 약한(관련성 낮은) 항목을 잘라낸다. 단 최소 keep_min개는 유지.
    items 는 score 내림차순으로 가정(retrieve 가 정렬해 반환)."""
    if not items:
        return items
    top = items[0].get("score") or 0
    if top <= 0:
        return items
    strong = [d for d in items if (d.get("score") or 0) >= ratio * top]
    return strong if len(strong) >= keep_min else items[:keep_min]


# 검색 관련도 판정에서 무시할 범용어 — 어디에나 나와서 '관련 있음' 신호가 못 된다.
_GENERIC_TERMS = {
    "ai", "인공지능", "딥러닝", "머신러닝", "llm", "모델", "기술", "시스템",
    "데이터", "정보", "연구", "개발", "기업", "산업", "서비스", "플랫폼",
    "활용", "도입", "적용", "솔루션", "디지털", "혁신", "성능", "효율",
    "비용", "사업", "시장", "출시", "공개", "발표", "생성", "생성형",
    # 질문/뉴스 문장에 흔히 섞이는 구조·지시어
    "우리", "논문", "뉴스", "근거", "파급효과", "분석해줘", "위해",
}


def _evidence_weak(question, docs, top=6):
    """내부 핵심 근거(논문/블로그)가 질문 주제와 직접 관련이 약한지 판단.
    질문의 '변별력 있는' 핵심어(범용어 제외)가 상위 근거 제목·요약에 거의 안 나오면 약함.
    → 약하면 웹 검색으로 보강한다."""
    key = [t for t in set(_tokens(question))
           if t not in _GENERIC_TERMS and len(t) >= 2]
    if not key:
        return False          # 변별 핵심어가 없으면 판단 불가 → 강제하지 않음
    if not docs:
        return True           # 내부 근거가 아예 없으면 약함
    hits = 0
    for d in docs[:top]:
        hay = (str(d.get("title", "")) + " " + str(d.get("summary", ""))).lower()
        if any(k in hay for k in key):
            hits += 1
    return hits < 2           # 상위 근거 중 핵심어 포함이 2건 미만이면 약함


def _first_sentence(text):
    """요약의 첫 문장(또는 첫 줄)만 한 줄 설명으로 쓴다.
    일부 요약은 마침표 없이 줄바꿈으로 구분되므로 첫 줄을 먼저 취한다."""
    t = (text or "").strip()
    if not t:
        return ""
    t = t.splitlines()[0].strip()                  # 줄바꿈형 요약 → 첫 줄
    parts = re.split(r"(?<=[.!?。])\s+", t)         # 한 줄 안에서 첫 문장
    return (parts[0] if parts else t).strip()


def _format_lookup_answer(docs, news):
    """조회형 답변: 검색된 자료를 LLM 없이 그대로 목록 마크다운으로 만든다.
    작은 모델이 20여 건을 옮기다 누락·환각하는 문제를 피하고 100% 정확하게 보여준다."""
    def line(d):
        date = str(d.get("published_date") or "").strip()
        head = d["title"] + (f" ({date})" if date else "")
        s = _first_sentence(d.get("summary"))
        row = f"- **{head}**" + (f" — {s}" if s else "")
        url = (d.get("url") or "").strip()
        if url.startswith("http"):
            row += f" [원문↗]({url})"      # 클릭 시 새 탭으로 원문 열기
        return row

    # 근거 풀은 '논문(paper)'과 '연구소 블로그(blog)'가 섞여 있으므로 유형별로 정확히 구분한다.
    papers = [d for d in docs if d.get("source_type") == "paper"]
    blogs = [d for d in docs if d.get("source_type") == "blog"]

    parts = []

    def section(title, items):
        if items:
            parts.append(("\n" if parts else "") + f"## {title}")
            parts.extend(line(d) for d in items)

    section("논문 자료", papers)
    section("블로그 자료", blogs)
    section("뉴스 자료", news)
    return "\n".join(parts) if parts else "관련 저장 자료를 찾지 못했습니다."


def _build_prompt(question, history=None, use_web=False):
    """질문으로 논문(검증 근거)+뉴스(최신 동향)[+웹(실시간)] 검색 후 프롬프트 구성.
    질문 유형(조회/분석)에 따라 개수·시스템 프롬프트·마무리 지시를 다르게 한다.
    (docs, news, web, user_prompt, system_prompt) 반환."""
    is_analysis = _is_analysis(question)
    # 분석형은 LLM 컨텍스트 비용 때문에 핵심 근거에 집중(적게).
    # 조회형은 LLM을 안 거치지만, 목록이 너무 길면 보기 어려우므로 '관련도 상위 N'으로 둔다.
    # (관련도가 뚝 떨어지는 항목은 _drop_weak 가 추가로 잘라 더 짧아질 수 있다.)
    doc_k, news_k, news_keep = (8, 6, 4) if is_analysis else (30, 20, 15)

    docs = retrieve(question, top_k=doc_k)
    news = retrieve(question, top_k=news_k, source_type="news")
    # 분석 중인 뉴스 자신이 근거로 딸려오는 자기참조 제거
    news = [n for n in news if n["title"][:25] not in question][:news_keep]

    # 조회형에서 자료가 많을 때, 관련성이 뚝 떨어지는 약한 항목은 잘라낸다(목록 품질 유지).
    if not is_analysis:
        docs = _drop_weak(docs)
        news = _drop_weak(news)

    # 분석형인데 내부 근거가 질문 주제와 약하면 웹 검색을 자동으로 켠다.
    # 주신호: 뉴스 카드 분석('[뉴스]'로 시작)은 코퍼스에 없는 특정 주제가 많아 웹이 필요.
    # 보조신호: 핵심어가 상위 근거에 거의 없으면(_evidence_weak) 약함으로 본다.
    # (조회형은 LLM·웹을 안 쓰고, 사용자가 이미 웹을 켰으면 그대로 둔다.)
    is_news = question.lstrip().startswith("[뉴스]")
    if is_analysis and not use_web and (is_news or _evidence_weak(question, docs)):
        use_web = True

    web = []
    if use_web:
        from insight.websearch import search_web
        web = search_web(question, max_results=5, fetch_top=2)

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
    web_ctx = "\n\n".join(
        f"[웹 {i+1}] {w['title']} ({w['url']})\n{(w['body'] or w['snippet'])[:1200]}"
        for i, w in enumerate(web)
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

    if is_analysis:
        tail = ("위 자료에 기반해 분석하라. 신뢰도는 논문 > 뉴스 > 웹 순으로 가중하되, "
                "웹 검색 결과는 최신 외부 동향을 보강하는 참고로만 활용하라. "
                "반드시 각 주장 끝에 근거 자료의 실제 번호를 [논문 1]·[뉴스 2]·[웹 3]처럼 "
                "대괄호로 인용하라(문자 'N'이 아니라 자료에 매겨진 실제 숫자).")
    else:
        tail = ("위 자료를 각 자료당 한 줄씩, '- **제목 (날짜)** — 한 문장 요약' 형식으로 "
                "논문 먼저·뉴스 나중에 정리해 보여줘라. "
                "라벨('제목:/날짜:/요약:')을 반복하거나 한 자료를 여러 줄로 쪼개지 말고, "
                "분석·파급효과·총평은 쓰지 마라.")

    user_prompt = (
        f"# 근거 논문 요약 (검증된 핵심 근거)\n{context}\n\n"
        + (f"# 참고 최신 뉴스 (동향 보조자료)\n{news_ctx}\n\n" if news_ctx else "")
        + (f"# 웹 검색 결과 (실시간 외부 정보·미검증, 참고용)\n{web_ctx}\n\n" if web_ctx else "")
        + f"{convo}"
        + f"# 질문/뉴스\n{question}\n\n"
        + tail
    )
    system_prompt = ANALYSIS_PROMPT if is_analysis else LOOKUP_PROMPT
    return docs, news, web, user_prompt, system_prompt


def _sources_of(docs, news=None, web=None):
    """근거 자료 목록(논문+뉴스+웹)을 프론트 표시용으로 직렬화.
    cite: 답변의 인용 표기와 일치하는 번호(프롬프트가 docs=[논문 N]·news=[뉴스 N]·web=[웹 N])."""
    out = [
        {
            "title": d["title"],
            "published_date": str(d["published_date"]),
            "meta": d["affiliations"] or d.get("source_name", ""),
            "url": d.get("url", ""),
            "kind": "블로그" if d.get("source_type") == "blog" else "논문",
            "cite": f"논문 {i + 1}",   # docs는 프롬프트에서 모두 [논문 N]으로 인용됨
            "score": d["score"],
        }
        for i, d in enumerate(docs)
    ]
    out += [
        {
            "title": d["title"],
            "published_date": str(d["published_date"]),
            "meta": d["authors"],
            "url": d.get("url", ""),
            "kind": "뉴스",
            "cite": f"뉴스 {i + 1}",
            "score": d["score"],
        }
        for i, d in enumerate(news or [])
    ]
    out += [
        {
            "title": w["title"],
            "published_date": "",
            "meta": w["url"],
            "url": w["url"],
            "kind": "웹",
            "cite": f"웹 {i + 1}",
            "score": 0,
        }
        for i, w in enumerate(web or [])
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
    docs, news, web, user_prompt, system_prompt = _build_prompt(
        question, payload.get("history"), use_web=bool(payload.get("web")))
    # 조회형은 LLM 없이 검색 결과를 그대로 목록화(정확·완전). 분석형만 LLM 호출.
    if not _is_analysis(question):
        answer = _format_lookup_answer(docs, news)
    else:
        try:
            answer = chat(system_prompt, user_prompt, max_tokens=4000)
        except Exception as e:  # noqa: BLE001
            return JsonResponse({"error": f"LLM 호출 실패: {e}"}, status=502)
    return JsonResponse({
        "answer": answer,
        "sources": _sources_of(docs, news, web),
        "provider": current_provider(),
    })


@require_GET
def api_models(request):
    """설치된 Ollama 모델 목록 + 현재 선택 모델. (엔진 토글용)"""
    provider = current_provider()
    models = list_ollama_models() if provider == "ollama" else []
    return JsonResponse({
        "provider": provider,
        "current": current_model(),
        "models": models,
    })


@require_POST
def api_set_model(request):
    """Ollama 모델을 런타임 전환(재시작 불필요). provider가 ollama일 때만 유효."""
    if current_provider() != "ollama":
        return JsonResponse({"error": "현재 provider가 ollama가 아닙니다."}, status=400)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "잘못된 요청"}, status=400)
    model = (payload.get("model") or "").strip()
    if not model:
        return JsonResponse({"error": "model이 필요합니다."}, status=400)
    # 실제 설치된 모델만 허용(오타·미설치 방지)
    installed = list_ollama_models()
    if installed and model not in installed:
        return JsonResponse({"error": f"설치되지 않은 모델: {model}"}, status=400)
    set_ollama_model(model)
    return JsonResponse({"ok": True, "model": model})


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

    docs, news, web, user_prompt, system_prompt = _build_prompt(
        question, payload.get("history"), use_web=bool(payload.get("web")))

    analysis = _is_analysis(question)
    allow_claude = bool(payload.get("allow_claude"))

    def sse(ev, obj):
        return f"event: {ev}\ndata: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    def event_stream():
        # 먼저 근거 출처를 한 번 보냄
        yield sse("sources", _sources_of(docs, news, web))
        # 조회형: LLM 없이 검색 결과를 그대로 목록화해 한 번에 보낸다(정확·완전).
        if not analysis:
            yield sse("token", {"t": _format_lookup_answer(docs, news)})
            yield sse("done", {})
            return
        # 분석형
        if current_provider() != "claude":
            # 로컬(ollama/exaone) 등 — 설정된 provider로 그대로 스트리밍 (하이브리드 미적용)
            try:
                for piece in stream(system_prompt, user_prompt, max_tokens=4000):
                    yield sse("token", {"t": piece})
            except Exception as e:  # noqa: BLE001
                yield sse("error", {"error": str(e)})
            yield sse("done", {})
            return
        # provider=claude(서버): Gemini(무료) 먼저 → 모든 모델 한도초과면 사용자 확인 후 Claude(유료)
        from insight.llm import gemini_analysis, GeminiExhausted, _stream_claude
        try:
            text, gmodel = gemini_analysis(system_prompt, user_prompt, 8000)
        except GeminiExhausted:
            if not allow_claude:
                # 사용자에게 Claude 사용 여부를 물어본다 (프론트에서 예/아니오)
                yield sse("confirm_claude", {
                    "message": "Gemini 무료 한도가 모두 소진되었습니다. Claude(유료) API로 분석하시겠습니까?"})
                return
            # 사용자가 승인 → Claude 스트리밍
            yield sse("engine", {"engine": "Claude"})
            try:
                for piece in _stream_claude(system_prompt, user_prompt, 8000):
                    yield sse("token", {"t": piece})
            except Exception as e:  # noqa: BLE001
                yield sse("error", {"error": str(e)})
            yield sse("done", {})
            return
        except Exception as e:  # noqa: BLE001
            yield sse("error", {"error": str(e)})
            return
        # Gemini 성공 → 통째로 전송 (Gemini 어댑터는 비스트리밍)
        yield sse("engine", {"engine": "Gemini", "model": gmodel})
        yield sse("token", {"t": text})
        yield sse("done", {})

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"  # nginx 버퍼링 방지
    return resp
