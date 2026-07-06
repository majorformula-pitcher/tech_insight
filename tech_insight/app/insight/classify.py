"""문서 카테고리 자동 분류(단일 문서). 수집기·백필이 공유하는 분류 SSOT.

taxonomy 자체는 insight/categories.py 가 기준([[category-taxonomy-ssot]]).
여기서는 그 카테고리의 '분류 설명문'(CLASSIFY_GUIDE)과 단건 분류 함수를 제공한다.

원칙: LLM 한 번 호출로 category 하나를 반환하고, 실패·무효 응답은 default('기타')로
폴백한다. 어떤 예외도 삼켜 **수집 흐름을 절대 막지 않는다**(뉴스/블로그/논문 저장이
분류 실패로 중단되면 안 됨).
"""
import json
import re

from insight.categories import CATEGORIES, CATEGORY_SET
from insight.llm import chat

# 카테고리 분류 기준 설명(프롬프트에 넣는 텍스트). backfill_categories 도 이걸 가져다 쓴다.
CLASSIFY_GUIDE = (
    "AI(인공지능·머신러닝·LLM·컴퓨터비전·음성), "
    "Robot(로봇·휴머노이드·자율주행·제어), "
    "Security(보안·암호·해킹·프라이버시), "
    "Data(데이터베이스·빅데이터·데이터엔지니어링·분석 인프라), "
    "IT(반도체·클라우드·네트워크·SW개발·기업/서비스 일반), "
    "Display(디스플레이·패널·OLED·LCD·색재현), "
    "기타(위에 안 맞음)"
)

_SYS = (
    "너는 기술 문서 분류기다. 문서를 다음 7개 중 정확히 하나로 분류한다: "
    + CLASSIFY_GUIDE + ". "
    '오직 JSON 객체 하나만 출력한다(설명·코드블록 금지). 형식: {"category":"AI"}'
)


def classify_category(title, summary="", *, default="기타"):
    """제목+요약으로 category 하나를 LLM 분류. 실패/무효 응답은 default('기타').

    수집 흐름을 막지 않도록 예외를 삼키고 default를 반환한다.
    """
    text = (title or "").strip()
    snip = (summary or "").replace("\n", " ").strip()[:400]
    if not text and not snip:
        return default
    try:
        raw = chat(_SYS, f"제목: {text[:200]}\n요약: {snip}", max_tokens=30)
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            cat = (json.loads(m.group(0)).get("category") or "").strip()
            if cat in CATEGORY_SET:
                return cat
        # JSON이 깨져도 응답 안에 카테고리 토큰이 그대로 있으면 회수(우선순위=CATEGORIES 순서)
        for c in CATEGORIES:
            if re.search(rf"(?<![A-Za-z]){re.escape(c)}(?![A-Za-z])", raw):
                return c
    except Exception:  # noqa: BLE001  분류 실패는 수집을 막지 않는다
        pass
    return default
