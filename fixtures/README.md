# Fixtures

Only privacy-checked fixtures belong here. `generated/` fixtures retain each
official CSV's public headers and null shape but replace **every non-null value**
with deterministic synthetic content. They are suitable for parser, projection,
and UI tests, not analytical assertions.

Regenerate after a reviewed schema change:

```bash
uv run mor-l0 redact-fixtures --all --rows 20
```
