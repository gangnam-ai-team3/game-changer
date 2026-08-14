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

### 출시 전 업데이트 점검

웹 화면에서 `업데이트 점검`을 선택하면 무기 밸런스, UI·UX, 시스템·규칙
변경안의 **출시 전 예상**과 출시 후 확인 지표를 분리해 볼 수 있습니다. 기본
Dragunov 사례는 확률형 피해(기본 58·최대 73)를 고정 피해 60으로 바꾸는
변경안입니다.

기본 fixture의 75개 자료는 [PUBG Update 25.2 패치 노트](https://pubg.com/en/news/6616)와
변경 조건을 바탕으로 만든 비식별 합성 비교 참고 자료입니다. 모두
`synthetic=true`, `comparable_reference`이며 실제 사용자 여론이나 업데이트 후
실제 반응이 아닙니다. 따라서 fixture 결과는 실제 사후 반응을 0건으로
해석하지 않고, 출시 후 확인할 지표만 제시합니다.

- `fixture`: 외부 API 없이 재현 가능한 Dragunov 시연 경로입니다.
- `live`: Steam/X를 사용자가 명시적으로 선택한 경우에만 기준일 이전 기간을
  수집합니다. 연결 실패·표본 부족·분류 실패는 fixture로 대체하지 않고
  `PARTIAL` 결과와 `판정 보류(Hold)`로 남깁니다.
- `import`: 승인된 UTF-8 CSV(2 MB 이하)만 받습니다. 원문·사용자명·계정 ID
  열과 기준일 이후/`after` 행은 거부합니다.

API와 웹 화면은 각각 별도 터미널에서 실행합니다.

```bash
# terminal 1: repository root
uv sync --extra dev --locked
cp backend/.env.example backend/.env
# backend/.env에만 필요 시 Claude 키를 로컬로 설정
uv run --env-file backend/.env uvicorn backend.app.main:app --reload --port 8000

# terminal 2: frontend/
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Claude는 선택적인 한국어 설명 보강에만 사용하며, 근거 ID·위험·지표·최종
판정은 결정론 코드가 소유합니다. `backend/.env.example`의 모델 선택 변수와
공유 예산 기본값($5, 최대 3회)을 유지하세요. `ANTHROPIC_API_KEY`는
`backend/.env` 또는 실행 환경에만 두고 Git·요청 payload·SSE·로그·채팅에
넣지 마세요. 키가 없거나 거절·예산 한도가 발생하면 fixture는 결정론적 안전
경로로 전환됩니다.

전체 검증은 다음과 같이 실행합니다.

```bash
uv run pytest
uv run python -m evaluation.verify_success
uv run python -m evaluation.verify_update_success
uv run python -c "from backend.app.main import app; assert app.title == 'Game Changer API'"
cd frontend && npm run build
```
