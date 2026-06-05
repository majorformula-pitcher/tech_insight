"""
PDF 본문 텍스트 추출 (다단 편집 대응).

문제: 정보과학회지 본문은 좌/우 2단(two-column) 편집이다.
pdfplumber로 그냥 추출하면 "왼쪽 줄 + 오른쪽 줄"이 한 줄로 섞여 문장이 깨진다.
게다가 첫 페이지는 [헤더(제목)] + [오른쪽 저자] + [2단 본문]처럼 영역이 섞여 있어
페이지 전체를 무조건 좌/우로 자르면 저자 줄이 본문 오른쪽 컬럼에 끼어든다.

해결: 페이지를 먼저 '세로 여백' 기준으로 가로 블록(밴드)으로 나눈다.
그러면 헤더·저자 블록과 본문 블록이 분리된다. 그다음 각 밴드마다
1단/2단을 따로 판정한다. 헤더(제목·저자)는 1단으로, 본문 블록만 2단으로 읽는다.
2단은 '여러 줄로 이루어진 충분히 큰 블록'에서만 적용해 제목이 잘못 쪼개지는 것을 막는다.
"""
from __future__ import annotations

import statistics

import pdfplumber


def _cluster_lines(words, y_tol=3.0):
    """단어들을 같은 줄(y좌표 근접)끼리 묶어 위->아래, 왼->오른쪽으로 정렬해 텍스트화."""
    if not words:
        return ""
    # top(=y) 기준 정렬 후 줄 단위로 묶기
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines = []
    cur, cur_top = [], None
    for w in words:
        if cur_top is None or abs(w["top"] - cur_top) <= y_tol:
            cur.append(w)
            cur_top = w["top"] if cur_top is None else cur_top
        else:
            lines.append(cur)
            cur, cur_top = [w], w["top"]
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        ln = sorted(ln, key=lambda w: w["x0"])
        out.append(" ".join(w["text"] for w in ln))
    return "\n".join(out)


def _line_height(words):
    """단어 높이의 중앙값(줄 높이 추정). 밴드 분리 임계값 계산에 사용."""
    hs = [w["bottom"] - w["top"] for w in words if w["bottom"] > w["top"]]
    return statistics.median(hs) if hs else 10.0


def _split_bands(words):
    """
    단어들을 줄(line)로 묶은 뒤, 줄 사이 세로 간격이 크게 벌어지는 곳에서
    가로 블록(밴드)으로 나눈다. 반환: 밴드 리스트(각 밴드는 word 리스트).

    예) 첫 페이지: [제목 밴드] [저자 밴드] [본문 밴드] 로 분리된다.
    """
    if not words:
        return []
    lh = _line_height(words)
    # 줄 단위로 묶기 (top 근접)
    ws = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines = []  # (top, bottom, [words])
    cur, ctop, cbot = [], None, None
    for w in ws:
        if ctop is None or abs(w["top"] - ctop) <= lh * 0.6:
            cur.append(w)
            ctop = w["top"] if ctop is None else min(ctop, w["top"])
            cbot = w["bottom"] if cbot is None else max(cbot, w["bottom"])
        else:
            lines.append((ctop, cbot, cur))
            cur, ctop, cbot = [w], w["top"], w["bottom"]
    if cur:
        lines.append((ctop, cbot, cur))

    # 줄 사이 간격이 줄높이의 1.6배보다 크면 밴드 경계로 본다
    bands = []
    band = list(lines[0][2])
    prev_bottom = lines[0][1]
    for top, bottom, lws in lines[1:]:
        gap = top - prev_bottom
        if gap > lh * 1.6:
            bands.append(band)
            band = []
        band.extend(lws)
        prev_bottom = bottom
    if band:
        bands.append(band)
    return bands


def _band_gutter(words, page_width):
    """이 밴드가 2단이면 좌/우를 가르는 x경계를 반환, 1단이면 None."""
    # 줄 수가 너무 적은 밴드(제목·저자 등)는 2단으로 보지 않는다
    tops = {round(w["top"]) for w in words}
    if len(words) < 30 or len(tops) < 4:
        return None
    centers = sorted(((w["x0"] + w["x1"]) / 2) for w in words)
    lo, hi = page_width * 0.40, page_width * 0.60
    band = [c for c in centers if lo <= c <= hi]
    if not band:
        return page_width / 2  # 중앙이 완전히 비었으면 명확한 2단
    gaps = [(band[i + 1] - band[i], (band[i + 1] + band[i]) / 2)
            for i in range(len(band) - 1)]
    if not gaps:
        return None
    max_gap, mid = max(gaps, key=lambda g: g[0])
    return mid if max_gap >= 12 else None


def _render_band(words, page_width):
    """밴드 1개를 텍스트로. 2단이면 좌->우 순서로, 1단이면 줄 단위로."""
    gutter = _band_gutter(words, page_width)
    if gutter is None:
        return _cluster_lines(words)
    left = [w for w in words if (w["x0"] + w["x1"]) / 2 < gutter]
    right = [w for w in words if (w["x0"] + w["x1"]) / 2 >= gutter]
    return (_cluster_lines(left) + "\n" + _cluster_lines(right)).strip()


def extract_page(page) -> str:
    """페이지 1장에서 영역(밴드)을 나눠 컬럼 순서를 지켜 텍스트 추출."""
    words = page.extract_words(use_text_flow=False)
    if not words:
        return page.extract_text() or ""
    bands = _split_bands(words)
    return "\n".join(_render_band(b, page.width) for b in bands).strip()


import re

# 문단이 끝났다고 볼 수 있는 줄 끝 (문장부호 또는 한국어 종결어미)
_SENTENCE_END = re.compile(r"(?:[.!?。:;」』”\"\)\]]|[다요음함됨임])\s*$")
# 글머리표·번호·제목처럼 보이는 줄 (새 줄로 유지)
_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s|[-•▪·○∙*]\s|[<\[【])")


def unwrap_lines(text: str) -> str:
    """
    PDF의 '보이는 줄' 단위 강제 줄바꿈을 문단 단위로 다시 이어붙인다.

    규칙:
    - 빈 줄은 문단 구분으로 유지
    - 현재 줄이 문장부호/한국어 종결어미로 끝나면 줄바꿈 유지(문단 끝)
    - 다음 줄이 번호·글머리표·제목 형태면 줄바꿈 유지
    - 그 외에는 다음 줄과 한 칸 띄워 이어붙임(줄 중간에서 잘린 문장 복원)
    - 영어 단어가 하이픈(-)으로 잘린 경우 하이픈 제거하고 붙임
    """
    lines = [ln.rstrip() for ln in text.split("\n")]
    out = []
    buf = ""
    for raw in lines:
        ln = raw.strip()
        if not ln:
            if buf:
                out.append(buf)
                buf = ""
            out.append("")  # 빈 줄(문단 구분) 유지
            continue
        if not buf:
            buf = ln
            continue
        # 이전 줄이 종결됐거나, 이번 줄이 제목/글머리표면 → 줄 끊기
        if _SENTENCE_END.search(buf) or _HEADING.match(ln):
            out.append(buf)
            buf = ln
        elif buf.endswith("-") and buf[-2:-1].isalpha():
            buf = buf[:-1] + ln          # 영어 하이픈 단어 이어붙이기
        else:
            # 한글끼리 또는 일반 연결 → 공백으로 이어붙임
            buf = buf + " " + ln
    if buf:
        out.append(buf)
    # 연속된 빈 줄은 하나로
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return result.strip()


def extract_pdf(pdf_path, unwrap: bool = True) -> str:
    """PDF 전체에서 2단 편집을 고려해 본문 텍스트를 추출한다.

    unwrap=True 면 PDF의 줄 단위 강제 개행을 문단 단위로 정리한다.
    """
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(extract_page(page))
    text = "\n".join(parts).strip()
    if unwrap:
        text = unwrap_lines(text)
    return text
