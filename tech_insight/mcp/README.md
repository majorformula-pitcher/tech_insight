# Tech Insight MCP 서버

기술문서 코퍼스(논문·블로그·뉴스)를 **Claude에서 도구로 조회**하기 위한 MCP 서버.
조회 전용 REST API(`/api/v1`)를 감싼 얇은 래퍼로, **데이터만 반환**한다(답변 생성은 Claude가 함 → 이 서버는 LLM 비용 없음).

## 제공 도구

| 도구 | 설명 |
|---|---|
| `search_documents(query, category, source_type, date_from, date_to, limit)` | 의미검색 → 요약+메타+링크 |
| `get_document(doc_id)` | 단건 상세 |
| `list_metadata()` | 카테고리·출처유형·문서수 |

> 원문 전문(raw_text)은 저작권상 제공하지 않는다(요약+링크만). 벡터 분석이 필요하면 REST API의 `/embeddings`를 직접 사용.

## 설치

```bash
pip install -r requirements.txt      # mcp, httpx
```

## 설정

환경변수 두 개가 필요하다:
- `TECHINSIGHT_API`   : 조회 API 베이스 URL (예: `http://168.107.27.0:8000/api/v1`)
- `TECHINSIGHT_TOKEN` : 발급받은 토큰

### Claude Desktop

`claude_desktop_config.json` 에 추가:
```json
{
  "mcpServers": {
    "tech-insight": {
      "command": "python",
      "args": ["/절대경로/techinsight_mcp.py"],
      "env": {
        "TECHINSIGHT_API": "http://168.107.27.0:8000/api/v1",
        "TECHINSIGHT_TOKEN": "발급토큰"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add tech-insight \
  --env TECHINSIGHT_API=http://168.107.27.0:8000/api/v1 \
  --env TECHINSIGHT_TOKEN=발급토큰 \
  -- python /절대경로/techinsight_mcp.py
```

## 사용 예 (Claude 대화)

> "저장된 데이터 중 2025년 로봇 분야 논문 트렌드 정리해줘"

→ Claude가 `search_documents(query="로봇", category="Robot", source_type="paper", date_from="2025-01-01", date_to="2025-12-31")` 를 호출하고, 받은 요약들로 답변을 구성한다.

## 참고

- 이 서버는 **stdio 전송**(각자 PC에서 실행 → Claude Desktop/Code)이다.
- claude.ai 웹의 "커스텀 커넥터"로 쓰려면 원격 HTTPS(Streamable-HTTP) 호스팅 + 공개 URL + 인증이 별도로 필요하다.
