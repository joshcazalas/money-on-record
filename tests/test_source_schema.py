from money_on_record_l0.source_schema import metadata_field_map


def test_maps_bulk_display_header_to_api_field_name() -> None:
    columns = [
        {"name": "Form", "fieldName": "form_type"},
        {"name": "View_Report", "fieldName": "link_to_report"},
        {"name": "Contribution_Amount", "fieldName": "contribution_amount"},
    ]

    assert metadata_field_map(columns) == {
        "form": "form_type",
        "form_type": "form_type",
        "view_report": "link_to_report",
        "link_to_report": "link_to_report",
        "contribution_amount": "contribution_amount",
    }
