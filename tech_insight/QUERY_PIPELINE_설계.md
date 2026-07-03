# 질문 이해·검색 파이프라인 설계 (Query Pipeline)

> 상태: **리뷰용 초안** (2026-07-03) · 코드 구현 전
> 목적: 어제의 땜질(“키워드 0건이면 키워드 빼고 재시도”)을 걷어내고,
> **모든 질문 유형을 일관된 구조로 처리**하는 파이프라인을 확정한다.

---

## 0. 결정 사항 (확정됨)

| 항목 | 결정 |
|------|------|
| 구현 범위 | **핵심만** — 하드/소프트 분리 + 규칙기반 날짜 + 닫힌집합 검증 + 정직한 빈결과. 집계(count)는 이번 범위 제외(다음 단계). |
| 명시 하드 제약 0건 | **정직하게 알림** — 몰래 조건 완화 안 함. “2024년 로봇 논문은 저장돼 있지 않습니다(2023·2025년은 있음)”. |
| 검증 순서 | **로컬(Ollama)에서 먼저 검증 → 확정 후 Oracle(Gemini) 확장**. |
| 의도 분류 | **규칙 우선** — 분석은 기존 `_is_analysis` 유지, search/browse는 슬롯 기반 자동 결정(LLM 추가 호출 없음). |
| 출처명 별칭 | **생략** — `source_name`은 부분일치(icontains). 별칭표는 필요 시 나중에. |
| category 미채움 | **논문·블로그도 LLM 백필** → category 하드필터를 모든 문서 유형에 적용. |

---

## 1. 문제 진단 — 왜 땜질이 됐나

어제 “openai 사업 관련 데이터” → 0건 사건의 진짜 원인:
**파서가 성격이 다른 두 가지를 `keyword` 하나에 뭉쳤다.**

| 종류 | 예시 | 올바른 처리 | 어제의 처리 |
|------|------|------------|------------|
| **하드 제약**(메타데이터) | "2024년", "로봇", "논문" | DB에서 정확히 일치만 남김 (filter) | — |
| **소프트 의도**(주제) | "openai 사업", "LLM 추론" | 벡터+키워드로 순위만 (rank) | `icontains` 하드필터 → 0건 |

`"openai 사업"`은 **주제(soft)**인데 `title LIKE '%openai 사업%'`로 하드필터를 걸어 전멸했다.
“0건이면 키워드 빼기”는 이 혼동을 **덮은 것**일 뿐, 언제 키워드가 하드인지/소프트인지 구분하지 못한다.

### 핵심 원칙
> **하드 제약(정확히 걸러야 할 메타데이터)과 소프트 의도(순위만 매길 주제)를 파서 단계부터 분리한다.**
> 주제는 절대 하드 필터로 걸지 않는다 — 그게 벡터 검색의 존재 이유다.
> 애매하면 항상 soft(semantic)로 흘려보낸다 → 결과가 사라지지 않는다.

---

## 2. 데이터 모델 (필터 가능한 실제 필드)

`Document` (insight/models.py) 기준:

| 필드 | 타입 | 하드 필터 대상 | 비고 |
|------|------|:---:|------|
| `published_date` | Date | ✅ 연·월·기간 | null 가능 |
| `category` | Char(30) | ✅ | 닫힌 집합: AI/Robot/Security/Data/IT/기타 |
| `source.type` | Choice | ✅ | 논문(PAPER)/뉴스(NEWS)/블로그(BLOG) |
| `source.name` | Char | ✅ | "OpenAI", "arXiv", "정보과학회지" 등 |
| `authors` | Char(500) | ✅ | 쉼표 구분, "오현옥 교수" |
| `affiliations` | Char(500) | ✅ | 쉼표 구분, "삼성", "KAIST" |
| `title`,`summary` | Text | ❌ 소프트 | 주제 매칭 → 벡터/키워드 랭킹 |
| `embedding` | Binary | ❌ | bge-m3 벡터 (랭킹용) |

> **원칙:** 위 표에서 “하드 필터 대상 ✅”인 필드에만 filter를 건다. `title`/`summary`(주제)는 **절대 하드 필터 금지** → 랭킹만.

---

## 3. 파이프라인 (4계층)

```
질문(자연어)
  │
  ├─[1] 의도 분류(intent)  ── search / browse / analysis   (count는 다음 단계)
  │
  ├─[2] 슬롯 추출(slots)   ── hard{메타} + semantic_query{주제} 분리
  │        · 날짜는 규칙기반 파서가 먼저 확정
  │        · 카테고리/출처는 닫힌 집합 검증
  │        · 애매하면 semantic_query로
  │
  ├─[3] 쿼리 계획(plan)    ── hard → WHERE / semantic → 랭킹 / sort·limit
  │
  └─[4] 실행(execute)      ── 필터로 후보 → 하이브리드 랭킹 → 정직한 빈결과
```

### [1] 의도 분류 (intent)

| intent | 트리거 예 | 처리 |
|--------|----------|------|
| `analysis` | 카드 “파급효과 분석”, 분석 키워드 | 특정 문서 심층 분석 (기존 로직 유지) |
| `browse` | "2024년 로봇 논문 보여줘", "최근 AI 뉴스 5개" | 하드 필터 + **정렬 나열**(주제어 약함) |
| `search` | "openai 사업 관련 자료", "작년 LLM 동향" | 하드 필터 + **하이브리드 랭킹**(주제 중심) |
| ~~`count`~~ | ~~"작년에 논문 몇 개?"~~ | *(이번 범위 제외 — 다음 단계 DB 집계)* |

> search vs browse 구분은 **“주제어가 핵심인가(=search) / 목록 나열이 핵심인가(=browse)”**.
> 실무상 둘의 실행 경로는 거의 같고(필터+랭킹), 차이는 **정렬 기본값**뿐:
> browse=최신순, search=관련도순. 초기 구현은 `sort` 슬롯 하나로 통합 가능.

### [2] 슬롯 스키마 (파서 출력)

flat `keyword` 폐기. DB 필드와 1:1 매핑되는 타입 있는 슬롯:

```jsonc
{
  "intent": "search",              // search | browse | analysis
  "hard": {                        // 정확히 일치해야 할 메타데이터만
    "date_from": "2025-01-01",     // 규칙기반 파서가 채움 (ISO)
    "date_to":   "2025-12-31",
    "category":  null,             // ∈ {AI,Robot,Security,Data,IT,기타} | null
    "source_type": null,           // ∈ {paper,news,blog} | null
    "source_name": null,           // "OpenAI" 등 부분일치 | null
    "author":    null              // authors/affiliations 부분일치 | null
  },
  "semantic_query": "openai 사업 전략",  // 주제 — 오직 벡터/키워드 랭킹용
  "sort":  "relevance",            // relevance | date_desc
  "limit": null                    // 정수 | null
}
```

핵심 변화:
- **`keyword`(하드) 제거.** 주제는 항상 `semantic_query`(soft).
- 하드 슬롯은 전부 **실제 메타 필드**(날짜·카테고리·출처·저자)에만 매핑.
- 각 슬롯은 **스키마 검증 통과분만 사용**(아래 §4).

### [2-a] 규칙 기반 날짜 파서 (LLM에 맡기지 않음)

LLM은 날짜 계산("작년"→2025)을 자주 틀린다. **날짜만 규칙으로 확정**하고 LLM엔 주제·카테고리 판단만 맡긴다.

| 표현 | 해석 (오늘=2026-07-03 기준) |
|------|------|
| "2024년", "24년" | 2024-01-01 ~ 2024-12-31 |
| "25년 3월", "2025년 3월" | 2025-03-01 ~ 2025-03-31 |
| "올해" | 2026-01-01 ~ 오늘 |
| "작년" | 2025-01-01 ~ 2025-12-31 |
| "재작년" | 2024 전체 |
| "최근 3개월", "지난 6개월" | 오늘−N개월 ~ 오늘 |
| "최근"(숫자 없음) | 날짜 제약 없음 (정렬만 최신순) |

> 구현: `date_from`/`date_to`(ISO 범위)로 통일 → 연/월/기간을 한 방식으로 처리.
> 정규식으로 우선 파싱하고, 못 잡은 부분만 LLM 결과를 참고(하이브리드).

### [3] 쿼리 계획 (plan)

슬롯 → 실행 스펙 변환:

| 슬롯 | 변환 |
|------|------|
| `date_from`/`date_to` | `published_date__range` |
| `category` | `category__iexact` (닫힌집합 통과 시) |
| `source_type` | `source__type__in=[…]` |
| `source_name` | `source__name__icontains` |
| `author` | `Q(authors__icontains) | Q(affiliations__icontains)` |
| `semantic_query` | 벡터 임베딩 + 키워드 토큰 랭킹(RRF) |
| `sort` | relevance=RRF점수 / date_desc=`-published_date` |
| `limit` | top_k 및 표시 개수 |

> **카테고리 주의:** 현재 `category`는 뉴스에서 주로 채워짐. 논문/블로그에 값이 없으면
> 카테고리 하드필터가 그들을 다 걸러낼 수 있음 → **category 필터는 source_type이 news이거나
> 명시적으로 뉴스를 조회할 때만 적용**(기존 retriever 규칙 유지).

### [4] 실행 & 빈결과 정책 (정직한 알림)

```
1. hard 필터로 후보군 조회
2. 후보 있으면 → semantic_query로 하이브리드 랭킹 → top_k 반환
3. 후보 0건이면:
   ├─ 명시적 하드 제약이 있었나? (사용자가 직접 말한 연도·카테고리 등)
   │    └─ YES → 몰래 완화하지 않는다.
   │             "○○ 조건에 해당하는 자료가 저장돼 있지 않습니다."
   │             + 인접 조건 힌트("2023·2025년은 있습니다") 제공
   └─ 추론된 soft 슬롯만 있었나?
        └─ 그 슬롯을 완화하고 재시도 (semantic이 처리)
```

> 어제 땜질과의 차이:
> - 땜질: **조건을 조용히 지우고** 엉뚱한 결과라도 냈다.
> - 신설계: **사용자가 명시한 조건은 지키고**, 없으면 없다고 정직히 말한다.
>   자동 완화는 “LLM이 추론해 넣은 불확실한 슬롯”에만 허용.

---

## 4. 신뢰성·폴백 (LLM이 틀려도 안 무너지게)

1. **스키마 검증**: 모든 슬롯을 타입·범위·닫힌집합으로 검증. 실패한 슬롯은 **버리고**(무시) 나머지로 진행.
   - year 2000~2100, month 1~12, category ∈ 6종, source_type ∈ 3종.
2. **날짜는 규칙 우선**(§2-a) — LLM 날짜 계산 신뢰하지 않음.
3. **애매하면 soft**: LLM이 메타인지 주제인지 확신 못 하면 → `semantic_query`로. 하드필터로 안 걸어 결과 안 사라짐.
4. **파서 전체 실패**(LLM 오류/JSON 깨짐) → `hard={}`, `semantic_query=원문`. 검색은 항상 동작.
5. **임베딩 실패** → 키워드 랭킹만으로 폴백(기존 retriever 유지).

---

## 5. 질문 유형별 처리 (검증 시나리오)

| 질문 | intent | hard | semantic | 기대 |
|------|--------|------|----------|------|
| "openai 사업 관련 자료" | search | — | openai 사업 전략 | OpenAI 문서 상위 ✅ |
| "저장된 LLM 25년 데이터" | search | date 2025 | LLM 언어모델 | 2025년만 ✅ |
| "작년 LLM 동향" | search | date 2025 | LLM 동향 | 2025년만 |
| "2024년 로봇 논문" | browse | date 2024, type=paper | 로봇 | 2024 논문, 최신순 |
| "오현옥 교수 논문" | browse | author=오현옥, type=paper | — | 저자 일치 |
| "OpenAI 블로그 안전성 글" | search | source_name=OpenAI, type=blog | AI 안전성 | 출처+주제 |
| "최근 AI 뉴스 5개" | browse | cat=AI, type=news, limit 5 | — | 최신 5건 |
| "2019년 양자컴퓨팅 논문"(없을 때) | browse | date 2019 | 양자컴퓨팅 | **“2019년 자료 없음” 정직 안내** |

---

## 6. 로컬 → Oracle 확장 전략

- **파서 LLM 호출은 `insight.llm.chat`을 그대로 사용** → provider 전환만으로 로컬(Ollama)/서버(Gemini) 대응.
- 로컬 검증 완료 후 Oracle에선 **파서를 Gemini 무료 티어로 라우팅**(쿼리마다 Claude 비용 회피).
- 규칙 기반 날짜 파서는 LLM 독립 → 로컬/서버 동일 동작.
- 배포는 기존처럼 **파일 단위 checkout**(query_parser.py, retriever.py, views.py)로, 준비되면 함께 반영.

---

## 7. 구현 시 변경 파일 (예정)

| 파일 | 변경 |
|------|------|
| `insight/query_parser.py` | 슬롯 스키마 전면 개편(hard/semantic 분리), 규칙기반 날짜 파서 추가, 검증 강화 |
| `insight/retriever.py` | `keyword` 하드필터 제거, `hard` 슬롯(date range/source/author) 필터 계층, 정렬(sort) 반영, **어제의 graceful-degradation 제거** |
| `chatbot/views.py` | intent 분기, 빈결과 정직 안내 메시지, limit/sort 반영 |
| (신규) 날짜 파서 유닛 | "작년/25년/최근 3개월" 케이스 회귀 테스트 |

---

## 8. 결정 완료 (2026-07-03)

1. **intent 분류** → ✅ **규칙 우선** (분석=`_is_analysis` 유지, search/browse=슬롯 기반).
2. **source_name 표기 정규화** → ✅ **생략**(부분일치 icontains). 별칭표는 나중에.
3. **category 미채움** → ✅ **논문·블로그도 LLM 백필**(§9 작업에 포함).
4. **집계(count)** → 이번 범위 밖, 다음 단계 별도 실행 경로.

## 9. 구현 순서 (로컬 우선)

- [ ] **A. query_parser.py 재작성** — 슬롯 스키마(hard/semantic), 규칙기반 날짜, 검증, intent(규칙).
- [ ] **B. retriever.py 개편** — 하드 슬롯 필터(날짜범위·출처·저자), keyword 하드필터 및 어제 graceful-degradation 제거, sort 반영.
- [ ] **C. views.py** — intent 라우팅, 정직한 빈결과 안내, limit/sort.
- [ ] **D. category 백필 커맨드** — 논문·블로그를 LLM으로 6종 분류해 채움(로컬 Ollama).
- [ ] **E. 로컬 검증** — §5 시나리오 회귀 테스트.
- [ ] **F. (나중) Oracle 배포** — 파서를 Gemini 무료로 라우팅 후 파일단위 배포.
