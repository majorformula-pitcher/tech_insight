"""
임베딩 어댑터 — 텍스트를 의미 벡터로 변환한다. (LLM 어댑터 llm.py 와 같은 패턴)

환경변수:
    EMBED_PROVIDER = "ollama"(기본) | "openai"(클라우드 전환용, 미구현 자리)
    EMBED_MODEL    = "bge-m3"(기본)  ← 문서/질문 임베딩에 반드시 같은 모델 사용
    OLLAMA_URL     = "http://127.0.0.1:11434"(기본)

사용:
    from insight.embeddings import embed_texts, embed_one, current_model
    vecs = embed_texts(["문장1", "문장2"])   # -> [[...], [...]] (float 리스트)
"""
import json
import os
import urllib.request

DEFAULT_MODEL = "bge-m3"


def current_model() -> str:
    """현재 임베딩 모델 식별자 (provider:model). 문서에 기록해 pin 용도."""
    provider = os.environ.get("EMBED_PROVIDER", "ollama").lower()
    model = os.environ.get("EMBED_MODEL", DEFAULT_MODEL)
    return f"{provider}:{model}"


def _embed_ollama(texts: list[str]) -> list[list[float]]:
    model = os.environ.get("EMBED_MODEL", DEFAULT_MODEL)
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/embed", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("embeddings", [])


def embed_texts(texts: list[str]) -> list[list[float]]:
    """여러 텍스트를 임베딩. provider 에 따라 분기."""
    if not texts:
        return []
    provider = os.environ.get("EMBED_PROVIDER", "ollama").lower()
    if provider == "ollama":
        return _embed_ollama(texts)
    # 향후 클라우드 전환: openai/jina 등 여기에 추가
    raise RuntimeError(f"지원하지 않는 EMBED_PROVIDER: {provider}")


def embed_one(text: str) -> list[float]:
    """단일 텍스트 임베딩 (질문 검색용)."""
    out = embed_texts([text])
    return out[0] if out else []
