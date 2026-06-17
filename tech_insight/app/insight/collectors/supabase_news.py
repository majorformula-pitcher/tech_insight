"""
Supabase 'ai-bongchae' 테이블에서 팀이 선정한 뉴스를 가져온다 (PostgREST REST API).

연결정보는 환경변수로 받는다:
    SUPABASE_URL   예) https://xxxxx.supabase.co
    SUPABASE_KEY   anon 또는 service_role 키 (SUPABASE_ANON_KEY 도 허용)

테이블명에 하이픈이 있어(ai-bongchae) PostgREST 경로에 그대로 사용한다.
"""
import os

import requests

TABLE = "ai-bongchae"


def _conf():
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or ""
    if not url or not key:
        raise RuntimeError(
            "환경변수 SUPABASE_URL / SUPABASE_KEY(또는 SUPABASE_ANON_KEY)가 필요합니다.")
    return url, key


def fetch_news(limit: int = 0, since: str | None = None) -> list[dict]:
    """ai-bongchae 행 목록(created_at 내림차순).
    limit 0=전체, since='YYYY-MM-DD'이면 그 이후 created_at 만."""
    url, key = _conf()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    q = f"{url}/rest/v1/{TABLE}?select=*&order=created_at.desc"
    if since:
        q += f"&created_at=gte.{since}"
    if limit and limit > 0:
        q += f"&limit={limit}"
    r = requests.get(q, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()
