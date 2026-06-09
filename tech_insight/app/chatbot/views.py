"""
분석 챗봇 — 뉴스/질문을 받아 관련 논문 요약을 근거로 LLM이 분석 답변.
RAG: retrieve(관련문서) → 프롬프트 구성 → llm.chat() → 답변 + 출처.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from insight.llm import chat, current_provider
from insight.retriever import retrieve

SYSTEM_PROMPT = (
    "너는 한국 기술 트렌드 분석가다. 한국어로만 답한다. "
    "반드시 아래 제공된 '근거 논문 요약'에 기반해 분석하라. "
    "근거에 없는 내용은 추측하지 말고, 자료가 부족하면 그렇다고 밝혀라. "
    "답변은 ①핵심 분석 ②파급효과 ③근거가 된 논문 흐름 순으로 간결하게."
)


def index(request):
    """챗봇 페이지."""
    return render(request, "chatbot/index.html", {"provider": current_provider()})


@require_POST
def ask(request):
    """질문 처리: 관련 문서 검색 → LLM 분석 → JSON 응답."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "잘못된 요청"}, status=400)

    question = (payload.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "질문을 입력하세요."}, status=400)

    # 1) 관련 문서 검색
    docs = retrieve(question, top_k=5)

    # 2) 근거 컨텍스트 구성
    if docs:
        context = "\n\n".join(
            f"[논문 {i+1}] {d['title']} ({d['published_date']}, {d['affiliations']})\n요약: {d['summary']}"
            for i, d in enumerate(docs)
        )
    else:
        context = "(관련 논문을 찾지 못함)"

    user_prompt = (
        f"# 근거 논문 요약\n{context}\n\n"
        f"# 질문/뉴스\n{question}\n\n"
        f"위 근거에 기반해 분석하라."
    )

    # 3) LLM 호출
    try:
        answer = chat(SYSTEM_PROMPT, user_prompt, max_tokens=700)
    except Exception as e:  # noqa: BLE001
        return JsonResponse(
            {"error": f"LLM 호출 실패: {e}", "provider": current_provider()},
            status=502,
        )

    # 4) 응답 (답변 + 근거 출처)
    sources = [
        {
            "title": d["title"],
            "published_date": str(d["published_date"]),
            "authors": d["authors"],
            "affiliations": d["affiliations"],
            "score": d["score"],
        }
        for d in docs
    ]
    return JsonResponse({
        "answer": answer,
        "sources": sources,
        "provider": current_provider(),
    })
