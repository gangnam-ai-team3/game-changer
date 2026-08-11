# 합성 입력 재료 — Black Market 이벤트 검토

> 실제 이용자 자료가 아니며, 판단을 확인하기 위해 오류 두 가지를 일부러 포함했습니다.

## 변경안

- `run_id`: `res-day7-sample-001`
- `game`: PUBG: BATTLEGROUNDS
- `event_name`: Black Market 2025
- `cutoff_at`: `2025-06-11T00:00:00Z`
- `goal`: 이벤트 보상 교환 참여 확대
- `participation_rule`: 매일 미션을 완료해 토큰을 모은 뒤 보상 상자를 교환
- `rewards`: 무기 스킨, 장식 아이템, 교환 토큰
- `probability_guarantee`: 10회 교환마다 보너스 보상 1회 보장
- `monetization_policy`: 부족한 토큰은 유료 패스로 보충 가능
- `expiration_policy`: 이벤트 종료 시 남은 토큰은 사라짐

## 피드백 표본

| evidence_id | source | language | source_id | observed_at | summary | mechanism_tags |
| --- | --- | --- | --- | --- | --- | --- |
| `voc-001` | steam | en | `src-001` | 2025-05-10T09:00:00Z | 무작위 보상이라 원하는 아이템까지 필요한 횟수를 알기 어렵다는 의견 | random_bonus, opaque_progress |
| `voc-002` | reddit_import | ko | `src-002` | 2025-05-12T10:00:00Z | 매일 미션을 놓치면 보상을 따라잡기 어렵다는 의견 | grind_pressure, time_cost |
| `voc-003` | x | en | `src-001` | 2025-05-13T11:00:00Z | 보상 상자 확률보다 확정 교환 경로가 필요하다는 의견 | random_bonus, fairness |
| `voc-004` | reddit_import | pt-BR | `src-004` | 2025-05-14T12:00:00Z | 이벤트 종료 뒤 토큰이 사라지면 남은 재화가 손실된다는 의견 | expiring_currency, fairness |
| `voc-005` | steam | zh-CN | `src-005` | 2025-05-15T13:00:00Z | 유료 패스로 시간을 줄이는 구조가 불공정하게 느껴질 수 있다는 의견 | monetization, fairness |
| `voc-006` | x | ko | `src-006` | 2025-06-15T14:00:00Z | 이벤트 종료 직전에는 미션을 완료할 시간이 부족하다는 의견 | time_cost, expiring_currency |

## 일부러 넣은 흠

1. `voc-003`은 `voc-001`과 같은 익명 `source_id`인 `src-001`을 사용했습니다. 중복을 제거해야 합니다.
2. `voc-006`은 `cutoff_at` 이후에 관찰된 자료입니다. 사전검증 근거에서 제외해야 합니다.

## 기대하는 검토 포인트

- 남은 표본은 언어권별 일반 100건·관련 15건 기준에 훨씬 못 미칩니다.
- 따라서 언어권별 고유 결론과 네 패널의 확정 반응을 만들면 안 됩니다.
- 표본 부족을 이유로 실습용 판단은 `Hold`로 남겨야 합니다.
