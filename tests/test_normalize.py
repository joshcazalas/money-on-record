from money_on_record_l0.normalize import (
    has_invalid_code_prefix,
    strict_name_key,
    suffix_candidate_key,
)


def test_strict_key_normalizes_typography_but_preserves_legal_suffix() -> None:
    assert strict_name_key("Café A&B, L.L.C.") == "CAFE A AND B LLC"
    assert strict_name_key("Husch Blackwell LLP") != strict_name_key("Husch Blackwell LP")


def test_suffix_key_creates_review_candidate_without_changing_strict_key() -> None:
    assert suffix_candidate_key("Husch Blackwell LLP") == "HUSCH BLACKWELL"
    assert suffix_candidate_key("Husch Blackwell LP") == "HUSCH BLACKWELL"


def test_miscellaneous_vendor_codes_are_rejected_by_prefix() -> None:
    assert has_invalid_code_prefix(" mis0000222 ", ("MIS",))
    assert not has_invalid_code_prefix("0000222", ("MIS",))
