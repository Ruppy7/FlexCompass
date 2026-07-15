# Public data source register

This register identifies public portals supported or planned by FlexCompass. A
portal being public does not mean every resource has the same licence or access
conditions. Dataset-level terms must be checked before redistribution.

| Owner | Official portal | API | Authentication | Licence status | Current limitation |
|---|---|---|---|---|---|
| National Grid Electricity Distribution | https://connecteddata.nationalgrid.co.uk | OpenDataSoft catalogue API | Some resources may use a public token | Unverified per dataset | Dataset identifiers and schemas need contract tests |
| SP Energy Networks | https://spenergynetworks.opendatasoft.com | OpenDataSoft catalogue API | Public token may be required for some resources | Unverified per dataset | Resource coverage and update schedules vary |
| Electricity North West | https://electricitynorthwest.opendatasoft.com | OpenDataSoft catalogue API | Some downloads may require a public account or token | Unverified per dataset | Login and download conditions vary by resource |
| Scottish and Southern Electricity Networks | https://data.ssen.co.uk | CKAN API | Varies by resource | Unverified per dataset | Resource formats and schemas vary |
| National Energy System Operator | https://www.neso.energy/data-portal | Research pending | To be verified | Unverified | Not yet integrated; catalogue technology and dataset contracts require research |

The repository stores catalogue metadata only. Downloaded portal responses,
caches, and generated databases are local artifacts and must not be committed.
