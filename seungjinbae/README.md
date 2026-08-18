# seungjinbae 작업 칸

- 담당자: 승진배
- 담당 범위: 근거 감사와 사업 실행 전략

이 폴더는 승진배 담당 에이전트의 실습 자료와 제출물을 보관합니다. 실제 회사 자료 대신 합성 자료만 사용합니다.

| 파일 | 용도 |
| --- | --- |
| `agent-spec.md` | 교안의 개인 명세서 여섯 칸을 정리한 제출물 |
| `input-sample.md` | 에이전트에 넣어 볼 합성 jelly 동향 표와 일부러 넣은 흠 |
| `stub.md` | 결과 모양 견본 |
| `result.md` | 입력을 감사한 실습 결과 |
| `screen.html` | 판정 로직을 그대로 재현한 연습용 화면 |

실습 순서는 `input-sample.md`를 읽고 `stub.md`의 모양으로 결과를 만든 뒤, `result.md`에서 판정과 사유를 확인하는 것입니다. `jelly/` 폴더가 넘긴 동향 표를 받아 `res/`·`hy/` 폴더의 실제 산출물과 대조하고, 표본이 부족한 결론은 통과시키지 않습니다.

## 파이프라인에서의 위치

```
hy(수집) → res(근거 구조화) → jelly(동향·위험 진단) → seungjinbae(근거 감사) → res(조립)
```

이 칸은 jelly의 동향 판정을 받아 통과/반려를 매기고, 그 결과를 다시 res가 `DecisionBrief`로 조립합니다. 실제 서브에이전트 정의는 `.claude/agents/seungjinbae.md`에 있으며, res.md는 `Agent(hy, jelly, seungjinbae)`로 이 이름을 직접 호출합니다.
