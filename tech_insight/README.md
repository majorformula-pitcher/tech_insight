# Tech Insight Platform

정보과학회지 등 기술 문헌을 수집·분석해 트렌드 인사이트를 제공하는 웹 서비스.
PDF 본문을 추출·DB화하고, 키워드/주제/시차 분석 대시보드를 제공한다.
(최종 목표: 논문·블로그·뉴스 확대 + RAG 기반 분석 챗봇 — `ARCHITECTURE.md` 참고)

## 기술 스택
- Django 6.0 (백엔드 + 관리자 + 대시보드)
- pdfplumber (2단 편집 대응 PDF 추출)
- SQLite (데이터베이스)

## 프로젝트 구조
```
tech_insight/
├── ARCHITECTURE.md      # 설계 문서·로드맵
├── README.md
├── data_source/         # 원본 PDF (GitHub 제외 — 용량 큼)
└── app/                 # Django 프로젝트
    ├── manage.py
    ├── requirements.txt
    ├── config/          # 설정
    ├── insight/         # 데이터 모델·PDF 파이프라인 (메뉴: Data Source)
    └── dashboard/       # 인사이트 대시보드
```

## 로컬 실행 (Windows)
```powershell
# 1) 가상환경 + 의존성
py -m venv venv
venv\Scripts\python.exe -m pip install -r tech_insight\app\requirements.txt

# 2) DB 마이그레이션 (db.sqlite3 동봉 시 생략 가능)
cd tech_insight\app
..\..\venv\Scripts\python.exe manage.py migrate

# 3) 서버 실행
..\..\venv\Scripts\python.exe manage.py runserver
# http://127.0.0.1:8000/admin (관리자)
# http://127.0.0.1:8000/dashboard (대시보드)
```

## 서버 배포 (Linux / Oracle Cloud)
`DEPLOY.md` 참고. 요약:
```bash
git clone <이 저장소>
cd <repo>/tech_insight/app
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# 환경변수 설정 (.env.example 참고)
export DJANGO_SECRET_KEY=... DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=<서버IP>
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

## PDF 데이터 적재 (원본 PDF가 있을 때)
```bash
python manage.py import_journal              # 정보과학회지 전체 적재
python manage.py import_journal --reextract  # 본문 재추출
python manage.py stats                       # 적재 현황
```
