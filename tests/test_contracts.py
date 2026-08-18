import pytest

from money_on_record_l0.contracts import ContractError, load_inventory


def test_inventory_has_six_unique_official_sources() -> None:
    inventory = load_inventory()

    assert len(inventory.sources) == 6
    assert len({source.dataset_id for source in inventory.sources.values()}) == 6
    assert inventory.require("campaign-contributions").role == "official_projection"
    assert inventory.require("contracts").role == "current_only"


def test_every_source_is_default_deny_with_an_explicit_allowlist() -> None:
    inventory = load_inventory()

    for source in inventory.sources.values():
        assert source.public_fields
        assert "address" in source.restricted_field_patterns
        assert not (set(source.public_fields) & set(source.restricted_fields))


def test_duplicate_yaml_keys_fail_closed(tmp_path) -> None:
    inventory = tmp_path / "sources.yaml"
    inventory.write_text("version: 1\nversion: 2\nsources: {}\n", encoding="utf-8")

    with pytest.raises(ContractError, match="duplicate YAML key"):
        load_inventory(inventory)
