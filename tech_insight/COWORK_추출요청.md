# Claude Cowork 추출 요청 프롬프트

아래 내용을 **Claude Cowork**에 그대로 붙여넣어 사용하세요.
(Cowork에 정보과학회지 PDF 폴더를 연결한 상태에서)

---

## 붙여넣을 프롬프트

```
C:\VS_Test\tech_insight\data_source\정보과학회지 폴더 안의 모든 PDF를 분석해서,
논문별 메타데이터를 추출해 엑셀(.xlsx) 파일 하나로 만들어줘.

[대상]
- 하위 월별 폴더(23_1, 23_2 ... 26_5)의 모든 PDF가 대상.
- 단, 아래 행정성 문서는 제외(논문이 아님):
  목차, 학회동정, 월별 특집계획, 월별 학술행사 개최계획,
  특집원고 모집, 학회지를 맡으면서, 취임사, "특집을 내면서"류

[엑셀 컬럼 — 정확히 이 7개, 영문 헤더로]
1. title         : 논문 제목 (PDF 파일명을 그대로 쓰면 됨)
2. authors       : 저자명. 여러 명이면 쉼표로 구분 (예: 박진영, 송길태)
3. affiliations  : 저자 소속. 여러 개면 쉼표로 구분 (예: 성균관대학교, 부산대학교)
4. published_date: 발행 연월. YYYY-MM-DD 형식, 일자는 01로 통일
                   (폴더명 26_5 → 2026-05-01)
5. raw_text      : 논문 본문 전체 텍스트.
                   ★ 중요: 2단(좌/우 컬럼) 편집이므로 왼쪽 단을 끝까지 읽은 뒤
                   오른쪽 단을 읽는 순서로 정리. 제목·저자·소속 줄은 본문에서 제외.
6. summary       : 논문 핵심 요약 3~5문장 (한국어). 무슨 주제를 다루고
                   어떤 결론/기여가 있는지 중심으로.
7. file_path     : data_source 기준 상대경로
                   (예: 정보과학회지\26_5\산업별 AGI 기술 활용...pdf)

[형식 규칙]
- 첫 행은 헤더(위 영문 컬럼명).
- 한 논문 = 한 행.
- 저자/소속을 PDF에서 못 찾으면 빈 칸으로 두기(임의로 지어내지 말 것).
- 결과 파일명: tech_insight_documents.xlsx

스캔(이미지) PDF라 텍스트가 안 나오면 raw_text는 비우고 나머지만 채워줘.
```

---

## 엑셀이 완성되면

1. 만들어진 `tech_insight_documents.xlsx` 파일을
   `C:\VS_Test\tech_insight\` 폴더에 둔다.
2. 적재 명령 실행:
   ```
   cd C:\VS_Test\tech_insight\app
   ..\..\venv\Scripts\python.exe manage.py import_excel ..\tech_insight_documents.xlsx --replace
   ```
   - `--replace` : 기존 정보과학회지 문서를 모두 지우고 엑셀 내용으로 새로 채움
3. 결과를 admin(문서 메뉴)에서 확인 → 저자·소속·요약이 채워졌는지 본다.

## 검증 포인트 (엑셀 받은 뒤)
- [ ] 행 수가 200편 안팎인지 (행정성 제외 후)
- [ ] authors/affiliations 가 본문이 아니라 별도 칸에 잘 분리됐는지
- [ ] raw_text 에 저자/제목 줄이 섞이지 않았는지
- [ ] published_date 가 YYYY-MM-DD 형식인지
