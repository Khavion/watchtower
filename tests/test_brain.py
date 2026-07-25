"""brain/ loaders: the machine-readable blocks parse and enforce their contracts."""

from pipeline import brain


def setup_function(_):
    brain.clear_cache()


def test_icp_filters_parse_with_verified_param_names():
    filters = brain.icp_filters()
    assert filters["organization_num_employees_ranges"] == ["20,200"]
    assert filters["include_similar_titles"] is False
    assert "cto" in filters["person_titles"]
    assert "amazon_aws" in filters["currently_using_any_of_technology_uids"]


def test_voice_rules_banned_list_and_em_dash():
    rules = brain.voice_rules()
    assert "i wanted to reach out" in rules["banned_phrases"]
    assert "—" in rules["banned_characters"]
    assert rules["max_words"] == 120


def test_proof_points_verified_only():
    verified = brain.proof_points(verified_only=True)
    assert verified, "verified proof points must exist"
    assert all(p["verified"] is True for p in verified)
    assert all(p.get("attribution") for p in verified), "every proof point carries attribution"


def test_rubric_hard_fail_present():
    r = brain.rubric()
    assert "blocklist_hit" in r["hard_fail"]
    assert set(r["account_criteria"]) == {"icp_fit", "cloud_footprint",
                                          "trigger_recency", "buyer_seniority",
                                          "contactability"}
