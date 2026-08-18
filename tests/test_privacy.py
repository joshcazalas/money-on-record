import csv

import pytest

from money_on_record_l0.contracts import load_inventory
from money_on_record_l0.privacy import PublicSchemaError, scan_public_csv


def _write_csv(path, fieldnames, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_unknown_or_restricted_field_fails_closed(tmp_path) -> None:
    path = tmp_path / "public.csv"
    _write_csv(path, ["donor", "donor_address"], [{"donor": "Example LLC", "donor_address": ""}])
    source = load_inventory().require("campaign-contributions")

    with pytest.raises(PublicSchemaError, match="not allowlisted"):
        scan_public_csv(path, source)


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("reach me at person@example.com", "email"),
        ("call (512) 555-0199", "phone"),
        ("office at 123 Main Street", "street_address"),
        ("identifier 123-45-6789", "ssn"),
    ],
)
def test_scans_values_even_in_allowlisted_text(tmp_path, value, kind) -> None:
    path = tmp_path / "public.csv"
    _write_csv(path, ["doc_dscr"], [{"doc_dscr": value}])
    source = load_inventory().require("contracts")

    findings = scan_public_csv(path, source)

    assert [finding.kind for finding in findings] == [kind]
    assert value not in findings[0].preview


def test_safe_public_projection_passes(tmp_path) -> None:
    path = tmp_path / "public.csv"
    _write_csv(
        path,
        ["donor", "donor_type", "contribution_amount"],
        [{"donor": "Example LLC", "donor_type": "Entity", "contribution_amount": "100.00"}],
    )
    source = load_inventory().require("campaign-contributions")

    assert scan_public_csv(path, source) == []
