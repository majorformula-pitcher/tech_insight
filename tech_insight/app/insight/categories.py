"""카테고리 taxonomy 단일 기준(SSOT).

파서·백필·뉴스수집·대시보드가 모두 여기를 참조한다. 카테고리를 추가/변경할 때
**이 파일만** 고치면 집합 검증(멤버십)은 전 지점에 자동 반영된다.
단, 각 LLM 프롬프트 안의 '카테고리 설명문'은 사람이 쓴 텍스트라 개별 수정이 필요하다.

표시 순서를 유지하며 '기타'는 항상 마지막에 둔다.
"""

CATEGORIES = ["AI", "Robot", "Security", "Data", "IT", "Display", "기타"]
CATEGORY_SET = set(CATEGORIES)

# 한국어 표시 라벨(대시보드·제약 설명문에서 사용)
CATEGORY_KO = {
    "AI": "AI",
    "Robot": "로봇",
    "Security": "보안",
    "Data": "데이터",
    "IT": "IT",
    "Display": "디스플레이",
    "기타": "기타",
}
