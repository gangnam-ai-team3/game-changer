# Task 2 Report: 결정론적 정책을 한 파일로 고정

## 결과

- `policy.py`에 정책 버전, 표본·신뢰도 기준, 위험 심각도 매핑, 개정안 매핑, 결정 우선순위를 중앙화했다.
- `event_redteam`은 중앙 `RISK_SPECS`를 사용한다.
- `audit_strategy`는 중앙 `MIN_RISK_CONFIDENCE`, `REVISION_SPECS`, `decide`를 사용한다.
- 기존 한국어 정책 문구는 변경하지 않았다.

## RED/GREEN evidence

RED:

```text
$ uv run pytest tests/test_policy.py -v
collected 0 items / 1 error
ModuleNotFoundError: No module named 'policy'
```

GREEN:

```text
$ uv run pytest tests/test_policy.py tests/test_agents.py -v
collected 11 items
11 passed in 0.02s

$ uv run pytest -v
collected 30 items
30 passed in 2.04s
```

## Files

- Added: `policy.py`
- Added: `tests/test_policy.py`
- Modified: `agents/event_redteam/agent.py`
- Modified: `agents/audit_strategy/agent.py`

## Self-review

- `git diff --check` passed.
- Decision precedence is explicitly covered by the six-table-case policy test: incomplete analysis, Critical, three insufficient languages, High, partial insufficiency, and Go.
- Existing agent tests cover centralized policy behavior through Revise/Hold flows.
- No protected `.claude/member` paths or later-task files were changed.

## Concerns

- `decide` accepts `analysis_incomplete` for callers that have incomplete AI analysis, while the current deterministic audit path intentionally calls it with the default as specified by Task 2.
