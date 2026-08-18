# Field dictionaries

Run `uv run mor-l0 freeze-metadata --all` followed by
`uv run mor-l0 field-dictionaries --all`. The generated dictionaries cite the
content-addressed metadata artifact and classify every observed field as:

- `PUBLIC_ALLOWLISTED`: eligible for a public projection;
- `RESTRICTED`: direct-contact/address-shaped field name; or
- `INTERNAL_REVIEW`: default-deny until explicitly reviewed.

Contract discrepancies are rendered at the top and must be resolved before a
profile or public projection is accepted.
