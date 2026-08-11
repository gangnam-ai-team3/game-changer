# seungjinbae/

"감시와 개선전략(ValidatedDecision)" 칸의 참고 자료 폴더입니다. 실제 에이전트 정의는 이 폴더가 아니라 저장소 루트의 [seungjinbae.md](../seungjinbae.md)와 `.claude/agents/validated-decision.md`에 있습니다. 이 폴더는 그 에이전트를 사용할 때 참고할 입력/출력 형태를 담습니다.

## 파일 구성

- **readme.md** — 이 파일. 폴더 구성 설명.
- **input-sample.md** — 에이전트에게 넘길 입력(리스크 서술 + 검증·개선 항목 목록)의 예시.
- **stub.md** — 실제 입력을 채워 넣기 위한 빈 템플릿.
- **result.md** — input-sample.md를 넣었을 때 나올 법한 출력(판정 표 + 총평)의 예시.

## 주의

input-sample.md와 result.md의 이름·수치·근거 ID는 형식을 보여주기 위해 만든 예시이며, 실제 VOC 데이터나 실행 결과가 아닙니다. 실제 실행 결과는 이 저장소의 `verify/` 폴더에 쌓입니다.
