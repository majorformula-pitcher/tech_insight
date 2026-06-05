# 배포 가이드 (GitHub → Oracle Cloud)

## 1단계. GitHub에 올리기 (로컬 PC에서)

### 1-1. GitHub에서 빈 저장소 생성
1. https://github.com/new 접속
2. Repository name: `tech-insight` (원하는 이름)
3. Public 선택
4. **README/.gitignore/license 체크 안 함** (이미 로컬에 있음)
5. "Create repository" 클릭

### 1-2. 로컬에서 push (생성 후 나오는 주소 사용)
```powershell
cd C:\VS_Test
git branch -M main
git remote add origin https://github.com/<사용자명>/tech-insight.git
git push -u origin main
```
- push 시 GitHub 로그인 창이 뜨면 브라우저로 인증
- 이후 코드 수정 → `git add -A && git commit -m "메시지" && git push`

---

## 2단계. Oracle Cloud 서버에 배포 (SSH 접속 후)

> 전제: Ubuntu 서버에 SSH 접속 가능

### 2-1. 필수 패키지 설치
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx
```

### 2-2. 코드 내려받기
```bash
cd ~
git clone https://github.com/<사용자명>/tech-insight.git
cd tech-insight/tech_insight/app
```

### 2-3. 가상환경 + 의존성
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2-4. 환경변수 설정
```bash
# 새 비밀키 생성
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# 아래를 ~/.bashrc 끝에 추가 (값은 본인 것으로)
export DJANGO_SECRET_KEY='위에서-생성한-키'
export DJANGO_DEBUG=0
export DJANGO_ALLOWED_HOSTS='<서버공인IP>'

# 적용
source ~/.bashrc
```

### 2-5. DB 준비 + 정적파일 모으기
```bash
python manage.py migrate
python manage.py collectstatic --noinput
# 관리자 계정 (db.sqlite3 동봉 시 이미 admin/admin1234 있음 — 비번 변경 권장)
python manage.py changepassword admin
```

### 2-6. gunicorn 으로 실행 테스트
```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000
# 브라우저에서 http://<서버IP>:8000/dashboard 접속 테스트 (Ctrl+C로 종료)
```

### 2-7. 방화벽 / 포트 개방 (중요!)
Oracle Cloud는 **2곳** 모두 열어야 한다:

**(A) Oracle 웹콘솔 — Security List**
1. 인스턴스 → VCN → Security List → Ingress Rules
2. Add: Source `0.0.0.0/0`, Protocol TCP, Dest Port `80` (및 테스트용 `8000`)

**(B) 서버 내부 방화벽**
```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save   # 재부팅 후에도 유지
```

### 2-8. 상시 실행 (systemd 서비스 등록)
```bash
sudo nano /etc/systemd/system/techinsight.service
```
내용:
```ini
[Unit]
Description=Tech Insight Gunicorn
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/tech-insight/tech_insight/app
Environment="DJANGO_SECRET_KEY=위에서-생성한-키"
Environment="DJANGO_DEBUG=0"
Environment="DJANGO_ALLOWED_HOSTS=<서버공인IP>"
ExecStart=/home/ubuntu/tech-insight/tech_insight/app/venv/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now techinsight
sudo systemctl status techinsight   # 동작 확인
```

이제 http://<서버공인IP>:8000/dashboard 로 상시 접속 가능.

> 80포트(http://IP/)로 깔끔하게 쓰려면 nginx 리버스 프록시를 8000→80으로 연결. 필요 시 추가 안내.

---

## 코드 업데이트 반영 (배포 후)
```bash
cd ~/tech-insight && git pull
cd tech_insight/app && source venv/bin/activate
pip install -r requirements.txt          # 의존성 변경 시
python manage.py migrate                 # 모델 변경 시
python manage.py collectstatic --noinput # 정적파일 변경 시
sudo systemctl restart techinsight
```
