# 근거 감사 및 검증 판정 에이전트 (Evidence Audit & Verification Judgment Agent) — 설계 문서

- 작성일: 2026-08-18
- 상태: 승인 대기 (스펙 리뷰용)

## 1. 목적

RAG/챗봇 등이 생성한 LLM 응답이 제공된 소스 문서(청크)에 실제로 근거하는지를 검증하는 백엔드 API 서비스. 응답을 문장(claim) 단위로 분해하여 각 claim이 소스에 근거하는지(grounded/not_grounded/partially_grounded)를 판정하고, 근거가 된 청크를 인용하며, 판정 이력을 저장한다.

## 2. 범위

- **검증 대상**: LLM 응답의 근거(grounding) — hallucination 탐지
- **사용 형태**: 다른 시스템(챗봇, RAG 파이프라인)이 호출하는 API/서비스
- **판정 단위**: 문장(claim) 단위 + 근거 인용 (전체 응답에 대한 단일 바이너리 판정이 아님)
- **판정 로직**: LLM을 심판자로 사용 (Claude API)
- **입력**: 이미 검색된 소스 청크 목록 (ID + 텍스트). 이 서비스는 검색(retrieval)을 수행하지 않음
- **청크 규모**: 요청당 대규모(수백 개 이상) 또는 가변적 — 이 제약이 아키텍처 선택을 좌우함
- **이력 저장**: 감사 결과를 DB에 저장 (즉시 응답 후 폐기하지 않음)

## 3. 아키텍처

Python + FastAPI 백엔드. 클라이언트가 호출하는 동기 API로, 요청 내부에서 여러 단계의 LLM/임베딩 호출을 조합해 판정을 만든다.

### 핵심 컴포넌트

1. **Claim Extractor** — Claude API 호출 1회. 응답 텍스트를 개별 주장(claim) 단위로 분해한다. 구조화된 출력(tool use)으로 `[{claim_text}, ...]` 형태를 강제한다.
2. **Chunk Embedder** — 요청에 포함된 소스 청크들을 임베딩(Voyage AI 등)한다. 청크는 요청마다 달라지므로 영구 벡터DB가 아니라 **요청 범위(ephemeral)의 인메모리 인덱스**로 처리한다.
3. **Retriever** — claim마다 임베딩 유사도로 상위 N개(기본값 8) 후보 청크만 추린다. 이 압축 단계 덕분에 청크가 수백 개여도 LLM 컨텍스트가 항상 작게 유지된다.
4. **Judge** — claim + 후보 청크 N개를 Claude에 넣어 `grounded / not_grounded / partially_grounded` 판정, 인용 청크 ID, 짧은 근거 설명을 반환한다. claim들은 동시성 제한(세마포어, 기본값 5)을 두고 병렬 처리한다.
5. **Persistence** — 감사 요청, claim별 판정, 인용, 타임스탬프를 DB(운영: Postgres, 로컬/테스트: SQLite)에 저장한다.

### 검토했던 대안과 기각 이유

- **단일 패스 (전체 청크를 한 컨텍스트에)**: 구현은 가장 단순하지만, 청크 수백 개를 한 번에 컨텍스트에 넣으면 초과·비용 폭증·판정 품질 저하 위험이 크다. 청크가 대규모라는 제약과 맞지 않아 기각.
- **2단계 (추출 → claim별 판정, 단 전체 청크를 매번 컨텍스트에)**: 정확도는 높지만 claim마다 전체 청크를 넣으면 여전히 컨텍스트가 거대해져 비용·지연이 심각. 임베딩 압축 단계가 없어 채택하지 않음.
- **채택안 (3단계: 추출 → 임베딩 압축 → LLM 최종 판정)**: 컨텍스트 크기가 항상 작게 유지되고 비용이 예측 가능하여, 대규모·가변 청크 수라는 핵심 제약을 만족하는 유일한 현실적 방식.

### 전체 흐름

```
클라이언트
  → POST /audits
  → Claim Extractor (LLM 1회)
  → Chunk Embedder (요청 내 청크 전체 임베딩)
  → claim별: Retriever(top-N 후보 추출) → Judge(LLM 판정, 병렬·동시성 제한)
  → 집계(grounded_ratio 등)
  → DB 저장
  → 응답 반환
```

## 4. API 계약

### `POST /audits` — 감사 요청 생성 (동기 응답)

```jsonc
// Request
{
  "response_text": "...",
  "source_chunks": [
    { "id": "chunk-1", "text": "..." },
    { "id": "chunk-2", "text": "..." }
  ],
  "metadata": { "source_system": "chatbot-x", "conversation_id": "..." }  // 선택
}
```

```jsonc
// Response
{
  "audit_id": "uuid",
  "overall": { "grounded_ratio": 0.83, "claim_count": 6 },
  "claims": [
    {
      "claim_text": "...",
      "verdict": "grounded",           // grounded | not_grounded | partially_grounded | judgment_failed
      "citations": ["chunk-2"],
      "rationale": "..."
    }
  ],
  "created_at": "2026-08-18T..."
}
```

### `GET /audits/{audit_id}` — 저장된 감사 결과 조회

### `GET /audits?source_system=&from=&to=` — 이력 목록/필터 조회 (통계용)

## 5. 데이터 모델

- **`audits`**: `id`, `response_text`, `metadata`(jsonb), `grounded_ratio`, `claim_count`, `created_at`
- **`audit_claims`**: `id`, `audit_id`(FK), `claim_text`, `verdict`, `citations`(jsonb), `rationale`
- **`audit_source_chunks`**: `id`, `audit_id`(FK), `chunk_id`, `chunk_text` — 감사 시점 스냅샷. 나중에 "그때 무엇을 근거로 판단했는지"를 재현할 수 있도록 청크 원문도 함께 저장한다.

## 6. 에러 처리

- **LLM 호출 실패**(타임아웃/429 등): 지수 백오프로 최대 2회 재시도. 그래도 실패하면 해당 claim만 `verdict: "judgment_failed"`로 표시하고 나머지 claim은 정상 반환 — 전체 요청을 실패시키지 않는다.
- **LLM 출력이 스키마를 어길 때**: structured output/tool use로 형식을 강제. 파싱 실패 시 1회 재시도, 그래도 실패하면 `judgment_failed` 처리.
- **`source_chunks`가 빈 배열**: LLM 호출 없이 모든 claim을 자동으로 `not_grounded` 처리(근거 문서 자체가 없으므로) — 불필요한 비용 절감.
- **claim이 0개로 추출됨**(예: 응답이 인사말뿐): `claims: []`, `grounded_ratio: null` 반환.
- **동시성 제한**: claim별 병렬 판정 호출에 세마포어로 상한(기본값 5)을 두어 과도한 API 비용·레이트리밋을 방지.

## 7. 테스트 전략

- **단위 테스트**: claim 추출 파싱, 임베딩 검색(top-N 후보 선정) 로직. LLM 응답은 목(mock)으로 대체.
- **통합 테스트**: FastAPI 엔드포인트 전체 흐름을 목 LLM/임베딩으로 검증. CI에서는 실제 API를 호출하지 않는다.
- **골든 테스트셋**: (응답, 청크, 기대 판정) 쌍을 준비해 저지 프롬프트 변경 시 회귀를 잡아내는 회귀 테스트로 사용. 실제 API 호출을 포함하므로 CI 기본 스위트와는 분리해서 운영.

## 8. 향후 고려 사항 (이번 스펙 범위 밖)

- 인증/멀티테넌시 정책
- 비동기(폴링/웹훅) API 옵션 — claim 수가 매우 많아 동기 응답 지연이 문제가 될 경우
- 대시보드/통계 화면 (이력 조회 API는 이미 있으므로 후속 작업으로 분리 가능)
