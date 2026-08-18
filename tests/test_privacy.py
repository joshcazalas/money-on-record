import csv
from dataclasses import replace

import pytest

from money_on_record_l0.contracts import load_inventory
from money_on_record_l0.privacy import (
    PublicSchemaError,
    contains_pii,
    scan_public_csv,
    scan_source_csv,
)


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
        ("call (512)555-0199", "phone"),
        ("call 5125550199", "phone"),
        ("office at 123 Main Street", "street_address"),
        ("mail it to P.O. Box 1234", "street_address"),
        ("identifier 123-45-6789", "ssn"),
        ("identifier 123 45 6789", "ssn"),
    ],
)
def test_scans_values_even_in_allowlisted_text(tmp_path, value, kind) -> None:
    path = tmp_path / "public.csv"
    _write_csv(path, ["doc_dscr"], [{"doc_dscr": value}])
    source = load_inventory().require("contracts")

    findings = scan_public_csv(path, source)

    assert [finding.kind for finding in findings] == [kind]
    assert value not in findings[0].preview
    assert findings[0].preview == "[redacted]"


def test_safe_public_projection_passes(tmp_path) -> None:
    path = tmp_path / "public.csv"
    _write_csv(
        path,
        ["donor", "donor_type", "contribution_amount"],
        [{"donor": "Example LLC", "donor_type": "Entity", "contribution_amount": "100.00"}],
    )
    source = load_inventory().require("campaign-contributions")

    assert scan_public_csv(path, source) == []


def test_rejects_values_beyond_declared_header(tmp_path) -> None:
    path = tmp_path / "public.csv"
    path.write_text("doc_dscr\nsafe,person@example.com\n", encoding="utf-8")
    source = load_inventory().require("contracts")

    with pytest.raises(PublicSchemaError, match="beyond the declared CSV header"):
        scan_public_csv(path, source)


def test_rejects_nonpositive_finding_limit(tmp_path) -> None:
    path = tmp_path / "public.csv"
    _write_csv(path, ["doc_dscr"], [{"doc_dscr": "safe"}])
    source = load_inventory().require("contracts")

    with pytest.raises(ValueError, match="must be positive"):
        scan_public_csv(path, source, maximum_findings=0)


def test_does_not_treat_structured_identifier_as_phone(tmp_path) -> None:
    path = tmp_path / "public.csv"
    _write_csv(path, ["transaction_id"], [{"transaction_id": "5125550199"}])
    source = load_inventory().require("campaign-contributions")

    assert scan_public_csv(path, source) == []


def test_entity_name_safety_has_no_identifier_exemption() -> None:
    assert contains_pii("5125550199")
    assert contains_pii("123 Main Street")
    assert not contains_pii("Example Organization LLC")


def test_source_audit_scans_allowlisted_values_without_exporting_private_fields(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "private-source.csv"
    _write_csv(
        path,
        ["DOC_DSCR", "CONTRACT_CONTACT_EMAIL_AD"],
        [{"DOC_DSCR": "safe description", "CONTRACT_CONTACT_EMAIL_AD": "person@example.com"}],
    )
    source = replace(
        load_inventory().require("contracts"),
        public_fields=("doc_dscr",),
    )
    monkeypatch.setattr(
        "money_on_record_l0.privacy.resolved_source_header",
        lambda _fieldnames, _source, _root: {
            "doc_dscr": "DOC_DSCR",
            "contract_contact_email_ad": "CONTRACT_CONTACT_EMAIL_AD",
        },
    )

    assert scan_source_csv(path, source, root=tmp_path) == []
