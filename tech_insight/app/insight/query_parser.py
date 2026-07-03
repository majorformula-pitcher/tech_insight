"""질문 → 검색 계획(plan) 추출 (Query Parser).

설계: QUERY_PIPELINE_설계.md 참고. 핵심 원칙은
**하드 제약(정확히 걸러야 할 메타데이터)과 소프트 의도(주제)를 분리**하는 것.

 - 하드 슬롯(정확히 일치): date_from/date_to, category, source_type, source_name, author
 - 소프트(순위만): semantic_query  ← 주제는 절대 하드 필터로 걸지 않는다(벡터 랭킹이 담당)
 - 날짜는 규칙 기반으로 확정(LLM 날짜 계산 불신). 나머지 의미 판단만 LLM.
 - 검증 통과분만 사용. 실패/애매하면 soft(semantic)로 → 결과가 사라지지 않는다.
 - LLM 호출·JSON 파싱이 실패해도 (원문, {})로 폴백하므로 검색은 항상 동작한다.

반환: (semantic_query, plan)
    plan = {date_from,date_to,category,source_type,source_name,author,limit,sort,intent}
    (해당 없는 키는 생략)
"""
import calendar
import json
import re
from datetime import date

from insight.llm import chat

# 카테고리 닫힌 집합
_CATS = {"AI", "Robot", "Security", "Data", "IT", "기타"}
# 출처 유형 정규화 (한국어/영어 → 내부 코드)
_STYPE = {
    "paper": "paper", "논문": "paper", "저널": "paper",
    "news": "news", "뉴스": "news",
    "blog": "blog", "블로그": "blog",
}

# 최근성(정렬을 최신순으로) 신호어
_RECENCY = re.compile(r"최신|최근|요즘|근래|new\b", re.I)

# 카테고리 '명시 단어'(도메인 요청 신호). 질문에 이게 있을 때만 category를 하드필터로 유지한다.
# 특정 기술·제품·주제어(LLM, GPT, RAG …)는 category가 아니라 semantic_query로 → 과잉 제한 방지.
_CAT_CUES = {
    "AI": r"인공지능|머신러닝|딥러닝|(?<![A-Za-z])ai(?![A-Za-z])",
    "Robot": r"로봇|휴머노이드|(?<![A-Za-z])robot",
    "Security": r"보안|해킹|취약점|악성코드|암호|프라이버시|(?<![A-Za-z])security",
    "Data": r"빅데이터|데이터베이스|데이터\s*엔지니어|데이터\s*센터|(?<![A-Za-z])db(?![A-Za-z])",
    "IT": r"반도체|클라우드|네트워크|통신|소프트웨어|하드웨어|(?<![A-Za-z])it(?![A-Za-z])",
}

_SYS = (
    "너는 검색 질의 분석기다. 사용자의 한국어 질문에서 검색 조건을 추출해 "
    "JSON 객체 하나만 출력한다(설명·코드블록 금지). 날짜(연·월)는 다루지 말 것. "
    "필드: "
    "category(정확히 하나 또는 null: AI, Robot, Security, Data, IT, 기타), "
    "source_type(다음 중 하나 또는 null: paper(논문), news(뉴스), blog(블로그)), "
    "source_name(특정 매체·기관명 또는 null. 예: OpenAI, arXiv, 정보과학회지), "
    "author(저자·연구자·소속 이름 또는 null), "
    "limit(사용자가 원한 개수 정수 또는 null), "
    "semantic_query(의미 검색에 쓸 '주제'만 남긴 문구 — 연도·개수·매체·'보여줘' 등 조건어 제외). "
    "핵심: 주제어는 semantic_query에만 넣고, category/source/author가 확실할 때만 채운다. 애매하면 null. "
    "예) '작년 오픈AI 블로그에서 안전성 관련 글 5개' → "
    '{"category":null,"source_type":"blog","source_name":"OpenAI","author":null,'
    '"limit":5,"semantic_query":"AI 안전성"}'
)


def _norm_year(s: str) -> int:
    """'2025'→2025, '25'→2025 (두 자리는 2000년대)."""
    s = s.strip()
    return int(s) if len(s) == 4 else 2000 + int(s)


def _month_range(y: int, mo: int):
    last = calendar.monthrange(y, mo)[1]
    return f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{last:02d}"


def _shift_months(d: date, n: int) -> date:
    """d에서 n개월 뒤로(음수면 과거). 일자는 월말 보정."""
    total = (d.year * 12 + (d.month - 1)) + n
    y, mo = divmod(total, 12)
    mo += 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def parse_dates(q: str, today: date):
    """규칙 기반 날짜 파싱 → (date_from, date_to) ISO 문자열 또는 (None, None).

    LLM에 맡기지 않는다(상대표현·2자리연도 계산을 안정적으로 처리)."""
    # 1) 상대 연도 표현
    if re.search(r"재작년|재\s*작년", q):
        return f"{today.year - 2}-01-01", f"{today.year - 2}-12-31"
    if re.search(r"작년|지난\s*해|전년", q):
        return f"{today.year - 1}-01-01", f"{today.year - 1}-12-31"
    if re.search(r"내년|명년", q):
        return f"{today.year + 1}-01-01", f"{today.year + 1}-12-31"
    if re.search(r"올해|금년|올\s*한\s*해", q):
        return f"{today.year}-01-01", today.isoformat()

    # 2) '최근/지난 N (일|주|개월|달|년)' — 기간
    m = re.search(r"(?:최근|지난)\s*(\d{1,3})\s*(일|주|개월|달|년|년간|개월간)", q)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("일"):
            frm = date.fromordinal(today.toordinal() - n)
        elif unit.startswith("주"):
            frm = date.fromordinal(today.toordinal() - n * 7)
        elif unit.startswith("년"):
            frm = _shift_months(today, -12 * n)
        else:  # 개월/달
            frm = _shift_months(today, -n)
        return frm.isoformat(), today.isoformat()

    # 3) '연도 + 월'  예: 2025년 3월, 25년 3월
    m = re.search(r"(19\d{2}|20\d{2}|\d{2})\s*년\s*(\d{1,2})\s*월", q)
    if m:
        y = _norm_year(m.group(1))
        mo = int(m.group(2))
        if 1 <= mo <= 12 and 2000 <= y <= 2100:
            return _month_range(y, mo)

    # 4) '연도'  예: 2024년, 24년, 2024
    m = re.search(r"(19\d{2}|20\d{2})\s*년", q) or re.search(r"\b(19\d{2}|20\d{2})\b", q)
    if m:
        y = int(m.group(1))
        if 2000 <= y <= 2100:
            return f"{y}-01-01", f"{y}-12-31"
    m = re.search(r"\b(\d{2})\s*년", q)          # '24년' 같은 2자리
    if m:
        y = _norm_year(m.group(1))
        if 2000 <= y <= 2100:
            return f"{y}-01-01", f"{y}-12-31"

    # 5) 단독 'N월' (연도 없음) → 올해 그 달
    m = re.search(r"(?<!\d)(\d{1,2})\s*월(?!\s*\d)", q)
    if m:
        mo = int(m.group(1))
        if 1 <= mo <= 12:
            return _month_range(today.year, mo)

    return None, None


def _clean_semantic(q: str) -> str:
    """LLM 실패 시 fallback semantic — 조건어 대충 제거(있는 그대로도 검색은 됨)."""
    return q


def parse_query(question: str, today: date | None = None):
    """(semantic_query, plan) 반환. plan은 하드 슬롯+limit+sort+intent.
    실패해도 (원문, {})로 폴백하므로 검색은 항상 동작한다."""
    q = (question or "").strip()
    if not q:
        return q, {}

    today = today or date.today()
    plan = {}

    # --- 날짜: 규칙 기반(항상 시도) ---
    df, dt = parse_dates(q, today)
    if df and dt:
        plan["date_from"] = df
        plan["date_to"] = dt

    # --- 나머지 슬롯 + 주제: LLM ---
    semantic = q
    try:
        raw = chat(_SYS, f"질문: {q}", max_tokens=200)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001  LLM/JSON 실패 → 날짜 규칙만 살리고 주제는 원문
        data = {}

    st = data.get("source_type")
    if isinstance(st, str) and st.strip().lower() in _STYPE:
        plan["source_type"] = _STYPE[st.strip().lower()]

    sn = data.get("source_name")
    if isinstance(sn, str) and sn.strip():
        plan["source_name"] = sn.strip()[:100]

    au = data.get("author")
    if isinstance(au, str) and au.strip():
        # 호칭 제거('오현옥 교수'→'오현옥') — authors 필드엔 이름만 있어 icontains가 어긋남
        au = re.sub(r"\s*(교수님|박사님|교수|박사|연구원|연구팀|대표|원장|소장|님|씨|ceo)\s*$",
                    "", au.strip(), flags=re.I).strip()
        if au:
            plan["author"] = au[:100]

    # category는 '확실할 때만' 하드필터로. LLM의 과잉 추론을 차단:
    #  - '기타'는 사실상 '모름' → 드롭
    #  - author가 있으면 사람 이름에서 분야를 추론한 것일 가능성이 커 드롭
    #  - 질문에 해당 분야의 '명시 단어'(로봇/보안/인공지능 등)가 있을 때만 유지.
    #    'LLM 관련 데이터'처럼 특정 주제어를 category(AI)로 바꿔 과잉 제한하는 것을 막는다.
    cat = data.get("category")
    if (isinstance(cat, str) and cat.strip() in _CATS and cat.strip() != "기타"
            and "author" not in plan
            and re.search(_CAT_CUES.get(cat.strip(), r"(?!x)x"), q, re.I)):
        plan["category"] = cat.strip()

    lim = data.get("limit")
    if isinstance(lim, int) and lim > 0:
        plan["limit"] = min(lim, 50)

    sem = data.get("semantic_query")
    if isinstance(sem, str) and sem.strip():
        semantic = sem.strip()

    # --- 정렬(규칙): 최근성 신호어 있으면 최신순 ---
    plan["sort"] = "date_desc" if _RECENCY.search(q) else "relevance"

    # --- intent(규칙, 간이): 분석은 views의 _is_analysis가 판단하므로 여기선 조회 계열만 ---
    plan["intent"] = "browse" if (plan.get("limit") or plan["sort"] == "date_desc") else "search"

    return semantic, plan
