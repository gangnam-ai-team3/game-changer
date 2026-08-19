## 함께 만들 때의 약속

- 폴더와 파일 이름은 영어로 짓는다
- 각자 자기 칸 자리만 손대고, 남의 칸은 말로 요청한다
- 회사 실제 자료는 올리지 않고, 예시 자료는 만들어 쓴다

## Claude Code 에이전트 구조

이 저장소의 에이전트 정의는 팀이 함께 쓰는 프로젝트 설정입니다. 현재는 담당자별 자리만 만들고, 내용은 각 담당자가 자신의 브랜치에서 작성해 PR합니다.

### 출시 전 업데이트 점검

자료 모드는 검증용 `fixture`, Steam과 X의 `live`, 승인된 CSV의 `import`, 미리 분류한 Steam `corpus`를 지원합니다. 자료가 부족하거나 외부 에이전트 검증이 끝나지 않으면 `PARTIAL`로 기록하고 판정 보류(Hold) 또는 결정론적 안전 경로로 전환합니다.

```bash
uv sync --extra dev --locked
uv run python -m evaluation.verify_update_success
uv run python -m hy.corpus build --db .data/corpus/pubg_steam.sqlite3 --target-per-language 500 --batch-size 20 --max-pages 20 --resume
uv run --env-file backend/.env uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

Steam 코퍼스 생성은 ChatGPT 구독으로 로그인한 Codex CLI를 사용합니다. 생성된 `.data/`는 로컬 시연 자료로만 유지하며 Git에 올리지 않습니다.

프론트엔드 배포 빌드는 `cd frontend && npm run build`로 확인합니다. API 키는 `backend/.env` 내부에만 보관하고 화면, 로그, Git에 남기지 않습니다.

```text
.claude/agents/        Claude Code가 읽는 역할 지시문
├─ hy.md               정현예 담당
├─ res.md              유주심 담당
├─ jelly.md            정아현 담당
└─ seungjinbae.md      승진배 담당

hy/                    정현예 작업 칸
res/                   유주심 작업 칸
jelly/                 정아현 작업 칸
seungjinbae/           승진배 작업 칸
```

- 각 담당자는 자신의 `.claude/agents/<이름>.md`와 동명 폴더만 수정합니다.
- 에이전트 정의에는 이름, 호출 시점, 도구와 핵심 지시를 포함합니다.
- 담당자는 자신의 브랜치에서 내용을 작성하고 PR을 요청합니다.
- 다른 담당자의 역할 파일은 직접 수정하지 않고 PR 검토 과정에서 의견을 남깁니다.
