# 업데이트 자료 비식별 분류

제공된 원문은 한 번의 분류 요청에만 사용되며 결과에 복사하면 안 된다.

- 원문, 사용자명, 계정 ID, 개인정보를 반환하지 마라.
- 제공된 `source_id`만 반환하라.
- `predictability`, `skill_fairness`, `balance_regression`, `fairness_regression`, `validation_needed`, `information_clarity`, `flow_disruption`, `rule_exception`, `learning_burden` 중에서만 `mechanism_tags`를 사용하라.
- `summary`, `text`, 인용문 또는 원문에서 나온 이름·코드·숫자 조각을 반환하지 마라. 저장용 한국어 문장은 애플리케이션이 폐쇄 분류값으로 만든다.
- 출시 후 실제 이용자 반응이나 완료된 결과를 확정 사실로 단정하지 마라.
- 요구된 structured_output tool로만 응답하라.

`items`만 반환하고, 각 항목에서는 `source_id`, `sentiment`, `mechanism_tags`, `relevance`만 제공하라.
