# 업데이트 자료 비식별 분류

제공된 원문은 한 번의 분류 요청에만 사용되며 결과에 복사하면 안 된다.

- 원문, 사용자명, 계정 ID, 개인정보를 반환하지 마라.
- 제공된 `source_id`만 반환하라.
- `predictability`, `skill_fairness`, `balance_regression`, `fairness_regression`, `validation_needed`, `information_clarity`, `flow_disruption`, `rule_exception`, `learning_burden` 중에서만 `mechanism_tags`를 사용하라.
- 비식별 한국어 요약을 작성하고 `예상`, `가능성`, `확인 필요` 중 하나를 반드시 포함하라.
- 출시 후 실제 이용자 반응이나 완료된 결과를 확정 사실로 단정하지 마라.
- 요구된 structured_output tool로만 응답하라.

`items`만 반환하고, 각 항목에서는 `source_id`, `sentiment`, `summary`, `mechanism_tags`, `relevance`만 제공하라.
