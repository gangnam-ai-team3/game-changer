# 게임체인저 발표 런북

## 발표 전 자동 확인

1. `uv sync --extra dev --locked`
2. `uv run pytest`
3. `uv run python -m evaluation.verify_success`
4. `uv run python scripts/smoke_steam.py --app-id 578080 --language en --limit 10`

Steam이 실패하면 오류와 확인 시각을 기록하고 저장 데이터 경로로 진행한다.

## 기본 시연

1. `uv run streamlit run streamlit_app.py`
2. `검증된 저장 데이터`를 선택한다.
3. 네 에이전트 카드가 모두 펼쳐지고 현재 내부 노드가 바뀌는지 확인한다.
4. 완료 후 `최종 판정: Revise`가 먼저 보이는지 확인한다.
5. 네 에이전트 추적 항목을 하나씩 펼쳐 계약과 근거 ID를 보여준다.
6. 같은 입력을 다시 실행하고 핵심 위험·근거·판정이 같은지 설명한다.

## 예외 시연

1. 근거 부족 fixture로 `Hold`를 보여준다.
2. LLM 설명 실패 시 규칙 기반 안전 경로 표시를 보여준다.
3. Steam 실시간 갱신 실패가 저장 데이터 결과를 덮어쓰지 않음을 보여준다.

## 강사 설명

> AI는 비정형 의견을 읽고 설명 후보를 만드는 분석가이고, 프로그램은 실제 근거와
> 고정 기준을 확인해 최종 판정을 내리는 심사위원·감사자입니다.

## 백업

- 1순위: 배포본
- 2순위: 로컬 실행본
- 3순위: 같은 시나리오의 화면 녹화본
