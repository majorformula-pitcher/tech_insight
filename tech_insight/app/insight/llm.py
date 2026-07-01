"""
LLM 어댑터 — 로컬(Ollama/EXAONE)과 Claude API를 환경변수로 전환한다.

환경변수:
    LLM_PROVIDER = "ollama"(기본) | "claude"
    OLLAMA_MODEL = "exaone3.5"(기본)
    OLLAMA_URL   = "http://127.0.0.1:11434"(기본)
    ANTHROPIC_API_KEY = (claude 사용 시)
    CLAUDE_MODEL = "claude-sonnet-4-6"(기본)

사용:
    from insight.llm import chat
    answer = chat(system="...", user="...")
"""
import json
import os
import urllib.request


# ── 토큰 사용량/비용 로깅 ──────────────────────────────────────────
# 모델별 단가 (USD per 1M tokens): (input, output)
_PRICING = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_USD_TO_KRW = 1400  # 참고용 환산 (실제 청구는 Anthropic 인보이스 기준)


def _log_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """Claude 토큰 사용량·예상비용을 token_usage.log 에 누적 기록. 실패해도 답변엔 영향 없음."""
    try:
        import datetime
        in_price, out_price = _PRICING.get(model, (3.0, 15.0))
        cost = input_tokens / 1_000_000 * in_price + output_tokens / 1_000_000 * out_price
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = (f"{ts}\tmodel={model}\tin={input_tokens}\tout={output_tokens}"
                f"\tcost_usd={cost:.6f}\tcost_krw={cost * _USD_TO_KRW:.1f}\n")
        # 이 파일 기준 app 디렉터리(.../app/token_usage.log)에 기록
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "token_usage.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:  # noqa: BLE001  로깅 실패가 답변을 막지 않도록
        pass


def _chat_ollama(system: str, user: str, max_tokens: int) -> str:
    model = os.environ.get("OLLAMA_MODEL", "exaone3.5")
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("message", {}).get("content", "").strip()


def _chat_claude(system: str, user: str, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 필요합니다.")
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # content: [{"type":"text","text":"..."}]
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    usage = data.get("usage", {})
    _log_usage(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    return "".join(parts).strip()


def chat(system: str, user: str, max_tokens: int = 600) -> str:
    """설정된 provider로 LLM 호출. 실패 시 예외."""
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    if provider == "claude":
        return _chat_claude(system, user, max_tokens)
    return _chat_ollama(system, user, max_tokens)


def _stream_ollama(system: str, user: str, max_tokens: int):
    model = os.environ.get("OLLAMA_MODEL", "exaone3.5")
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
        "think": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        for line in resp:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line.decode("utf-8"))
            piece = obj.get("message", {}).get("content", "")
            if piece:
                yield piece
            if obj.get("done"):
                break


def _stream_claude(system: str, user: str, max_tokens: int):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 필요합니다.")
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "stream": True,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    in_tok = 0
    out_tok = 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            raw = raw.strip()
            if not raw.startswith(b"data:"):
                continue
            data = raw[len(b"data:"):].strip()
            if data in (b"", b"[DONE]"):
                continue
            obj = json.loads(data.decode("utf-8"))
            otype = obj.get("type")
            if otype == "message_start":
                in_tok = obj.get("message", {}).get("usage", {}).get("input_tokens", 0)
            elif otype == "content_block_delta":
                piece = obj.get("delta", {}).get("text", "")
                if piece:
                    yield piece
            elif otype == "message_delta":
                out_tok = obj.get("usage", {}).get("output_tokens", out_tok)
    _log_usage(model, in_tok, out_tok)


def stream(system: str, user: str, max_tokens: int = 700):
    """설정된 provider로 토큰을 하나씩 yield 하는 스트리밍 호출."""
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    if provider == "claude":
        yield from _stream_claude(system, user, max_tokens)
    else:
        yield from _stream_ollama(system, user, max_tokens)


def current_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "ollama").lower()


def current_model() -> str:
    """현재 provider가 실제로 사용하는 LLM 모델명."""
    if current_provider() == "claude":
        return os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    return os.environ.get("OLLAMA_MODEL", "exaone3.5")
