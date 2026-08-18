import pytest

from money_on_record_l0.fields import canonical_field_name, canonical_header


def test_canonicalizes_display_headers() -> None:
    assert canonical_field_name("Contribution Amount") == "contribution_amount"
    assert canonical_field_name("Vendor/Customer #") == "vendor_customer"


def test_rejects_canonical_header_collision() -> None:
    with pytest.raises(ValueError, match="both map"):
        canonical_header(["Vendor Name", "vendor-name"])
