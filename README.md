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
uv run python -m res.corpus build-hy --source-db hy/steam-reviews.db --db .data/corpus/pubg_steam.sqlite3 --target-per-language 500 --batch-size 20 --max-pages 20
uv run --env-file backend/.env uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

Hy는 `hy/steam-reviews.db`에 PUBG Steam 원본과 수집 상태를 로컬로 준비합니다. Res는 한국어·영어 최초 백필이 완료된 시점까지의 자료만 사용하고, ChatGPT 구독으로 로그인한 Codex CLI를 통해 원문·Steam ID·공개 리뷰 ID·정확한 작성 시각이 없는 안전 코퍼스로 변환합니다. 생성된 `.data/`는 Git에 올리지 않습니다. 공개 시연본은 `uv run python -m res.corpus build-demo`로 재생성하며, 정의된 분류 값만 담은 `fixtures/corpus/pubg_steam_demo.sqlite3`만 배포합니다.

프론트엔드 배포 빌드는 `cd frontend && npm run build`로 확인합니다. API 키는 `backend/.env` 내부에만 보관하고 화면, 로그, Git에 남기지 않습니다.

## GitHub Codespaces 공개 시연

1. 저장소의 Codespaces secret에 `ANTHROPIC_API_KEY`를 등록합니다.
2. `demo_mvp` 브랜치로 Codespace를 만들고 초기 설치가 끝나면 `./scripts/start_codespace_demo.sh`를 실행합니다.
3. **Ports** 탭에서 3000 포트의 **Port Visibility**를 **Public**으로 바꾸고 표시된 URL을 공유합니다.

8000과 8787 포트는 공개하지 않습니다. Codespace를 다시 시작하면 공개 설정이 Private로 돌아가므로 시연 전에 3000 포트를 다시 Public으로 바꿔야 합니다. 시연이 끝나면 실행 스크립트를 `Ctrl+C`로 종료하고 Codespace도 정지합니다.

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
