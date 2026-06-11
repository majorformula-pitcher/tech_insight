"""
뉴스 Discovery API — ai-bongchae 구조 재현.
- 피드 목록 / 특정 피드 기사(실시간 RSS) / URL 추가(크롤링·요약·저장).
우리 insight.collectors.news 와 llm 을 재활용한다.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from insight.collectors.news import RSS_FEEDS, fetch_feed, extract_article
from insight.llm import chat
from insight.models import Source, Document

SUMMARY_SYSTEM = (
    "너는 뉴스 요약 전문가다. 한국어로만 답하고, 반드시 아래 JSON 형식으로만 출력한다.\n"
    '{"category": "AI/Robot/Security/Data/IT/기타 중 하나", '
    '"summary": ["문장1", "문장2", "문장3", "문장4"]}\n'
    "summary는 4문장, 각 문장은 '~입니다/~했습니다' 평어체, 숫자·불릿 금지, "
    "구체적 수치·고유명사·핵심 결과 포함."
)
CATEGORIES = ["AI", "Robot", "Security", "Data", "IT", "기타"]


def _parse_summary(raw):
    try:
        s = raw[raw.index("{"):raw.rindex("}") + 1]
        data = json.loads(s)
        cat = data.get("category", "기타")
        if cat not in CATEGORIES:
            cat = next((c for c in CATEGORIES if c.lower() in cat.lower()), "기타")
        summ = data.get("summary", "")
        if isinstance(summ, list):
            summ = "\n".join(str(x).strip() for x in summ if str(x).strip())
        return cat, summ
    except (ValueError, json.JSONDecodeError):
        return "기타", raw.strip()


@require_GET
def feeds(request):
    """RSS 피드 목록. id는 RSS_FEEDS의 인덱스."""
    data = [{"id": i, "name": name} for i, (name, _url) in enumerate(RSS_FEEDS)]
    return JsonResponse({"feeds": data})


@require_GET
def feed_items(request, feed_id):
    """특정 피드의 실시간 기사 목록. 이미 추가된 URL은 isAdded 표시."""
    try:
        name, url = RSS_FEEDS[int(feed_id)]
    except (ValueError, IndexError):
        return JsonResponse({"error": "잘못된 피드"}, status=400)
    items = fetch_feed(name, url, limit=20)
    added = set(Document.objects.filter(
        url__in=[it["url"] for it in items]
    ).values_list("url", flat=True))
    for it in items:
        it["isAdded"] = it["url"] in added
    return JsonResponse({"items": items, "feed": name})


@require_POST
def add_news(request):
    """URL 받아 크롤링·요약·저장 후 카드 데이터 반환 (+ 버튼)."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "잘못된 요청"}, status=400)
    url = (payload.get("url") or "").strip()
    title = (payload.get("title") or "").strip()
    if not url:
        return JsonResponse({"error": "url이 필요합니다."}, status=400)

    if Document.objects.filter(url=url).exists():
        return JsonResponse({"error": "이미 추가된 뉴스입니다.", "duplicate": True}, status=409)

    # 수동 모드: 사용자가 제목/요약/카테고리를 직접 입력 (크롤링 차단 사이트용)
    manual = payload.get("manual")
    if manual:
        m_title = (payload.get("title") or "").strip()
        m_summary = (payload.get("summary") or "").strip()
        m_cat = (payload.get("category") or "기타").strip()
        if not m_title:
            return JsonResponse({"error": "제목은 필수입니다."}, status=400)
        body, image = m_summary, ""
        category = m_cat if m_cat in CATEGORIES else "기타"
        # 요약을 안 줬으면 EXAONE으로 본문(=입력 요약)에서 정리, 줬으면 그대로
        summary = m_summary
        if m_summary and len(m_summary) > 150:
            try:
                raw = chat(SUMMARY_SYSTEM, f"제목: {m_title}\n\n본문:\n{m_summary[:4000]}", max_tokens=500)
                category, summary = _parse_summary(raw)
            except Exception:  # noqa: BLE001
                summary = m_summary
        title = m_title
    else:
        art = extract_article(url)
        body, image = art["body"], art["image"]
        if not body or len(body) < 80:
            # 크롤링 실패 → 프론트에 수동 입력 모드로 전환하라고 신호
            return JsonResponse({
                "error": "본문을 추출할 수 없습니다. (사이트 차단)",
                "needManual": True,
                "title": title,
            }, status=422)

        category, summary = "", ""
        try:
            raw = chat(SUMMARY_SYSTEM, f"제목: {title}\n\n본문:\n{body[:4000]}", max_tokens=500)
            category, summary = _parse_summary(raw)
        except Exception as e:  # noqa: BLE001
            return JsonResponse({"error": f"요약 실패: {e}"}, status=502)

    # pubDate(ISO/문자열)에서 날짜 부분만 (YYYY-MM-DD)
    pub = (payload.get("pubDate") or "")[:10]
    if len(pub) != 10 or pub[4] != "-":
        pub = None

    engine = "EXAONE" + (" (수동)" if manual else "")
    source, _ = Source.objects.get_or_create(name="뉴스", defaults={"type": Source.Type.NEWS})
    doc = Document.objects.create(
        source=source, title=title[:500] or "(제목 없음)",
        published_date=pub,
        raw_text=body, summary=summary, category=category,
        image=image[:1000] if image else "", url=url,
        authors=payload.get("source_name", ""), engine=engine,
        status=Document.Status.ANALYZED if summary else Document.Status.EXTRACTED,
    )
    return JsonResponse({"card": serialize_card(doc)})


def serialize_card(doc):
    """뉴스 카드 1건을 프론트 형식으로 직렬화."""
    return {
        "id": doc.id, "title": doc.title,
        "summary_lines": [s for s in (doc.summary or "").split("\n") if s.strip()],
        "summary": doc.summary, "category": doc.category or "기타",
        "image": doc.image, "source": doc.authors, "url": doc.url,
        "date": (f"{doc.published_date.year}. {doc.published_date.month}. {doc.published_date.day}."
                 if doc.published_date else ""),
        "engine": doc.engine,
        "created_at": doc.created_at.strftime("%Y.%m.%d %H:%M"),
    }


@require_POST
def edit_news(request, doc_id):
    """뉴스 카드 제목/요약/카테고리 수정."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "잘못된 요청"}, status=400)
    doc = Document.objects.filter(id=doc_id, source__name="뉴스").first()
    if not doc:
        return JsonResponse({"error": "없는 뉴스"}, status=404)
    if "title" in payload:
        doc.title = (payload["title"] or "").strip()[:500] or doc.title
    if "summary" in payload:
        doc.summary = (payload["summary"] or "").strip()
    if "category" in payload and payload["category"] in CATEGORIES:
        doc.category = payload["category"]
    doc.save(update_fields=["title", "summary", "category"])
    return JsonResponse({"card": serialize_card(doc)})
