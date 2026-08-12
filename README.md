## 함께 만들 때의 약속

- 폴더와 파일 이름은 영어로 짓는다
- 각자 자기 칸 자리만 손대고, 남의 칸은 말로 요청한다
- 회사 실제 자료는 올리지 않고, 예시 자료는 만들어 쓴다

## 게임체인저 서비스 실행

현재 MVP는 PUBG: BATTLEGROUNDS Black Market 사례를 네 에이전트가 순차 분석합니다.
기본 경로는 검증된 합성 입력을 사용하며, 결과를 미리 저장해 재생하지 않습니다.

```bash
uv sync --extra dev --locked
uv run pytest
uv run python -m evaluation.verify_success
uv run streamlit run streamlit_app.py
```

실시간 연결은 `.streamlit/secrets.toml.example`을 참고해 로컬 secrets를 설정합니다.
실제 secrets와 커뮤니티 원문은 Git에 추가하지 않습니다.

### 실시간 갱신 확인

`uv run python scripts/smoke_steam.py --app-id 578080 --language en --limit 10`

이 명령은 Steam의 현재 리뷰를 메모리에서 읽고 비식별화 여부만 확인합니다. 원문과
사용자 식별자는 저장하지 않습니다. 네트워크 장애 시 저장된 검증 데이터 시연은
계속 사용할 수 있습니다.

### 발표 런북

발표 전 확인, 기본·예외 시연, 백업 절차는 [발표 런북](docs/demo/2026-08-12-controlled-hybrid-demo-runbook.md)을 따릅니다.
