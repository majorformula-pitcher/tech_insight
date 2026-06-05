"""
기존 test/index.html 의 `const DATA = {...};` 블록을 뽑아
dashboard/static_data.json 으로 저장하는 1회성 스크립트.

JS 객체지만 정보과학회지 데이터는 순수 JSON 호환이라 json.loads로 파싱된다.
실행: python extract_static_data.py
"""
import json
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
INDEX = APP_DIR.parent / "test" / "index.html"
OUT = APP_DIR / "dashboard" / "static_data.json"

html = INDEX.read_text(encoding="utf-8")

# const DATA = { ... }; 블록 추출 (비탐욕 + 균형 중괄호)
m = re.search(r"const\s+DATA\s*=\s*(\{.*?\n\});", html, re.DOTALL)
if not m:
    raise SystemExit("DATA 블록을 찾지 못했습니다.")

obj_text = m.group(1)
data = json.loads(obj_text)

OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"저장 완료: {OUT}")
print(f"키 목록: {list(data.keys())}")
print(f"총 편수(static): {data.get('total_papers')}, 총 호수: {data.get('total_issues')}")
