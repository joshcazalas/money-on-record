from money_on_record_l0.acquire import project_root
from money_on_record_l0.contracts import load_inventory
from money_on_record_l0.versioned import validate_versioned_data


def test_checked_in_data_contract_is_self_consistent() -> None:
    summary = validate_versioned_data(load_inventory(), root=project_root())

    assert summary.metadata_artifacts == 6
    assert summary.profiles == 6
    assert summary.fixtures == 6
    assert summary.review_summaries == 0
