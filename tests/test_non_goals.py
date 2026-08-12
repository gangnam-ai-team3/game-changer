from contracts import DecisionBrief, EvidenceItem, Persona


def test_contracts_exclude_prediction_and_demographic_outputs():
    forbidden_outputs = {
        "revenue_prediction",
        "popularity_prediction",
        "individual_behavior_prediction",
        "country_generalization",
    }
    assert forbidden_outputs.isdisjoint(DecisionBrief.model_fields)
    assert {"age", "gender", "country"}.isdisjoint(Persona.model_fields)
    assert {"username", "handle", "raw_text"}.isdisjoint(EvidenceItem.model_fields)
