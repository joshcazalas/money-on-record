from money_on_record_l0.profile import TrackedField, _parse_date


def test_bulk_csv_dates_are_compared_chronologically() -> None:
    newer = _parse_date("01/01/2026")
    older = _parse_date("12/31/2025")

    assert newer is not None
    assert older is not None
    assert newer > older


def test_suspicious_years_are_counted_without_rewriting_source_value() -> None:
    field = TrackedField()

    field.observe(
        "12/02/0023",
        collect_distinct=False,
        collect_frequencies=False,
        collect_range=True,
    )

    assert field.minimum == "12/02/0023"
    assert field.suspicious_date_count == 1
    assert field.suspicious_date_examples == {"12/02/0023"}
