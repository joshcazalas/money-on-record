import csv
import json
from pathlib import Path

import pytest

from money_on_record_l0.candidates import CANDIDATE_FIELDNAMES
from money_on_record_l0.review import (
    REVIEW_FIELDNAMES,
    ReviewError,
    initialize_review,
    validate_review,
    validate_review_summary,
    write_review_summary,
)


def _candidate_row(
    candidate_id: str,
    *,
    tier: str = "A_STRICT",
    source: str = "contracts",
    campaign_name: str = "Example Campaign Organization",
    public_name: str = "EXAMPLE PUBLIC ORGANIZATION",
) -> dict[str, str]:
    row = {field: f"value-{field}" for field in CANDIDATE_FIELDNAMES}
    row.update(
        {
            "candidate_id": candidate_id,
            "evidence_tier": tier,
            "campaign_name": campaign_name,
            "public_record_name": public_name,
            "public_record_source": source,
            "public_record_code": f"CODE-{candidate_id[:4]}",
            "campaign_rows": "2",
            "public_record_rows": "3",
            "campaign_keys_for_suffix": "1",
            "public_keys_for_suffix": "1",
            "review_status": "UNREVIEWED",
            "same_organization": "",
            "external_evidence_url": "",
            "review_notes": "",
        }
    )
    return row


def _write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_review(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        return list(reader.fieldnames), [dict(row) for row in reader]


def _write_review(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _complete(
    row: dict[str, str],
    *,
    decision: str,
    reason: str,
    evidence: str,
) -> None:
    row.update(
        {
            "review_status": "COMPLETE",
            "same_organization": decision,
            "review_reason": reason,
            "external_evidence_url": evidence,
            "review_notes": "Independent records were inspected and documented.",
            "reviewer": "Test Reviewer",
            "reviewed_at": "2026-08-18T14:30:00-05:00",
        }
    )


def test_initialize_review_is_deterministic_and_refuses_overwrite(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review.csv"
    _write_candidates(candidates, [_candidate_row("a" * 16)])

    assert initialize_review(candidates, review) == review
    fieldnames, rows = _read_review(review)

    assert fieldnames[-len(REVIEW_FIELDNAMES) :] == list(REVIEW_FIELDNAMES)
    assert rows[0]["review_status"] == "UNREVIEWED"
    assert len(rows[0]["candidate_fingerprint"]) == 64
    with pytest.raises(ReviewError, match="refusing to overwrite"):
        initialize_review(candidates, review)


def test_validation_detects_immutable_evidence_edits(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review.csv"
    _write_candidates(candidates, [_candidate_row("a" * 16)])
    initialize_review(candidates, review)
    fieldnames, rows = _read_review(review)
    rows[0]["campaign_name"] = "Tampered Name"
    _write_review(review, fieldnames, rows)

    with pytest.raises(ReviewError, match="immutable candidate evidence was changed"):
        validate_review(review, candidates=candidates)


def test_validation_detects_candidate_set_drift(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review.csv"
    first = _candidate_row("a" * 16)
    _write_candidates(candidates, [first])
    initialize_review(candidates, review)
    _write_candidates(candidates, [first, _candidate_row("b" * 16)])

    with pytest.raises(ReviewError, match="missing 1 current candidate"):
        validate_review(review, candidates=candidates)


def test_unreviewed_rows_cannot_contain_partial_decisions(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review.csv"
    _write_candidates(candidates, [_candidate_row("a" * 16)])
    initialize_review(candidates, review)

    validation = validate_review(review, candidates=candidates)
    assert validation.unreviewed == 1
    with pytest.raises(ReviewError, match="review is incomplete"):
        validate_review(review, candidates=candidates, require_complete=True)

    fieldnames, rows = _read_review(review)
    rows[0]["same_organization"] = "YES"
    _write_review(review, fieldnames, rows)
    with pytest.raises(ReviewError, match="must not contain partial decisions"):
        validate_review(review, candidates=candidates)


def test_completed_review_writes_only_safe_aggregate_data(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review.csv"
    summary = tmp_path / "review-summary.json"
    rows = [
        _candidate_row(
            "a" * 16,
            campaign_name="Sensitive Candidate Alpha",
            public_name="SENSITIVE PUBLIC ALPHA",
        ),
        _candidate_row(
            "b" * 16,
            tier="B_LEGAL_SUFFIX",
            source="echeckbook",
            campaign_name="Sensitive Candidate Beta",
            public_name="SENSITIVE PUBLIC BETA",
        ),
    ]
    _write_candidates(candidates, rows)
    initialize_review(candidates, review)
    fieldnames, review_rows = _read_review(review)
    _complete(
        review_rows[0],
        decision="YES",
        reason="INDEPENDENT_OFFICIAL_IDENTITY",
        evidence="https://example.gov/entity/alpha",
    )
    _complete(
        review_rows[1],
        decision="NO",
        reason="DISTINCT_LEGAL_ENTITIES",
        evidence="https://example.gov/entity/beta | https://example.org/about",
    )
    _write_review(review, fieldnames, review_rows)

    assert write_review_summary(review, candidates, summary) == summary
    validate_review_summary(summary)
    report = json.loads(summary.read_text(encoding="utf-8"))
    serialized = json.dumps(report)

    assert report["complete"] is True
    assert report["totals"] == {"candidates": 2, "reviewed": 2, "unreviewed": 0}
    assert report["decisions"] == {"NO": 1, "UNCERTAIN": 0, "YES": 1}
    assert report["evidence_tiers"]["A_STRICT"]["reviewed"] == 1
    for private_value in (
        "Sensitive Candidate Alpha",
        "SENSITIVE PUBLIC BETA",
        "CODE-aaaa",
        "https://example.gov/entity/alpha",
        "Test Reviewer",
        "Independent records were inspected",
        "a" * 16,
    ):
        assert private_value not in serialized


def test_versioned_summary_contract_rejects_extra_candidate_data(tmp_path: Path) -> None:
    summary = tmp_path / "review-summary.json"
    summary.write_text(
        json.dumps(
            {
                "review_summary_version": 1,
                "candidate_set_sha256": "a" * 64,
                "complete": True,
                "totals": {"candidates": 1, "reviewed": 1, "unreviewed": 0},
                "decisions": {"YES": 1, "NO": 0, "UNCERTAIN": 0},
                "review_reasons": {"INDEPENDENT_OFFICIAL_IDENTITY": 1},
                "evidence_tiers": {
                    "A_STRICT": {
                        "total": 1,
                        "reviewed": 1,
                        "decisions": {"YES": 1, "NO": 0, "UNCERTAIN": 0},
                    }
                },
                "public_record_sources": {
                    "contracts": {
                        "total": 1,
                        "reviewed": 1,
                        "decisions": {"YES": 1, "NO": 0, "UNCERTAIN": 0},
                    }
                },
                "reviewed_through": "2026-08-18T14:30:00-05:00",
                "candidate_names": ["must not be versioned"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReviewError, match="fields do not match"):
        validate_review_summary(summary)


@pytest.mark.parametrize(
    ("decision", "reason", "evidence", "message"),
    [
        ("MAYBE", "INSUFFICIENT_EVIDENCE", "https://example.gov/a", "must be YES"),
        ("YES", "DISTINCT_LEGAL_ENTITIES", "https://example.gov/a", "invalid YES reason"),
        ("NO", "DISTINCT_LEGAL_ENTITIES", "http://example.gov/a", "durable HTTPS"),
    ],
)
def test_completed_review_requires_controlled_values(
    tmp_path: Path,
    decision: str,
    reason: str,
    evidence: str,
    message: str,
) -> None:
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review.csv"
    _write_candidates(candidates, [_candidate_row("a" * 16)])
    initialize_review(candidates, review)
    fieldnames, rows = _read_review(review)
    _complete(rows[0], decision=decision, reason=reason, evidence=evidence)
    _write_review(review, fieldnames, rows)

    with pytest.raises(ReviewError, match=message):
        validate_review(review, candidates=candidates)
