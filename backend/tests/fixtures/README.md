# SSEN NaFIRS HV test fixtures

These minimal rows were retrieved with unauthenticated, read-only HTTP GET
requests from the public SSEN Distribution dataset on 2026-07-30:

- Package: `https://data-api.ssen.co.uk/dataset/nafirs-hv-faults`
- SEPD resource: `ab32515f-76f2-421d-8034-7d5b01325a33`
- SHEPD resource: `673578c9-f531-41a5-a17c-0b35bc0fae4c`

Attribution: SSEN Distribution. The source is licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)
(`CC-BY-4.0`).

The retrieval used each stable SSEN resource URL without authentication,
validated the single public-storage redirect in memory, and retained only the
published header and minimal source rows. No signed redirect URL was retained.

The CKAN SEPD schema metadata reported `AVG_TIME_OFF_MINS`, while the
authoritative raw SEPD CSV header retrieved on 2026-07-30 was
`AVG_TIME_OFF_SUPPLY_MINS`.
