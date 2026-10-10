# Golden fixtures

These `.epro` files are **synthetic ZIP + JSON** archives built by
`scripts/build_fixtures.py`. Field names approximate public EasyEDA Pro
descriptions (`project.json`, `.epcb` / `.esch` style JSON).

**They are NOT the official complete EasyEDA Pro schema.**

| File | Purpose |
|------|---------|
| `simple.epro` | Clean 2-layer board; dry-run should PASS |
| `bus_mismatch.epro` | More nets; used with companion JSON for WARN/FAIL |
| `bus_mismatch_target_warn.json` | Target stats with 1 net rename → WARN |
| `bus_mismatch_target_fail.json` | Broken target → FAIL |
