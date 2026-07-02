"""질문에서 검색 조건과 의미 질의를 LLM으로 추출한다 (Query Parser).

현재 설정된 provider/model(insight.llm.chat)로 동작한다.
 - 로컬: 옵션에서 선택된 Ollama 모델(EXAONE/Qwen/Gemma2 등)
 - 서버: claude 등 (추후 gemini로 라우팅 확장 가능)

LLM 호출·JSON 파싱이 실패하면 필터 없이 원문 질의로 폴백하므로,
파서가 실패해도 검색 자체는 항상 동작한다(안전).
"""
import json
import re

from insight.llm import chat

_CATS = {"AI", "Robot", "Security", "Data", "IT", "기타"}

_SYS = (
    "너는 검색 질의 분석기다. 사용자의 한국어 질문에서 검색 조건을 추출해 "
    "JSON 객체 하나만 출력한다(설명·코드블록 금지). "
    "필드: "
    "year(정수 연도, '25년'은 2025로 해석), "
    "month(1~12 정수), "
    "category(다음 중 하나 또는 null: AI, Robot, Security, Data, IT, 기타), "
    "keyword(제목·저자에 포함돼야 할 핵심 단어 문자열 또는 null), "
    "limit(사용자가 원한 개수 정수 또는 null), "
    "semantic_query(의미 검색에 쓸 핵심 주제만 남긴 문구 — 연도·개수·'보여줘' 등 조건어는 제외). "
    "해당 없는 값은 null. "
    "예) '저장된 데이터 중 LLM 관련 25년 데이터 보여줘' → "
    '{"year":2025,"month":null,"category":null,"keyword":null,"limit":null,'
    '"semantic_query":"LLM 대규모 언어모델"}'
)


def parse_query(question: str):
    """(semantic_query, filters) 반환. 실패 시 (원문, {})."""
    q = (question or "").strip()
    if not q:
        return q, {}
    try:
        raw = chat(_SYS, f"질문: {q}", max_tokens=250)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001  LLM 오류·JSON 파싱 실패 → 폴백
        return q, {}

    filters = {}
    y = data.get("year")
    if isinstance(y, int) and 2000 <= y <= 2100:
        filters["year"] = y
    mo = data.get("month")
    if isinstance(mo, int) and 1 <= mo <= 12:
        filters["month"] = mo
    cat = data.get("category")
    if isinstance(cat, str) and cat in _CATS:
        filters["category"] = cat
    kw = data.get("keyword")
    if isinstance(kw, str) and kw.strip():
        filters["keyword"] = kw.strip()
    lim = data.get("limit")
    if isinstance(lim, int) and lim > 0:
        filters["limit"] = min(lim, 50)

    sem = data.get("semantic_query")
    semantic = sem.strip() if isinstance(sem, str) and sem.strip() else q
    return semantic, filters
