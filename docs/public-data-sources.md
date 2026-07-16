# Public data source register

This register identifies public portals supported or planned by FlexCompass. A
portal being public does not mean every resource has the same licence or access
conditions. Dataset-level terms must be checked before redistribution. Portal
and catalogue access was last checked on 15 July 2026.

| Owner | Official portal | Public catalogue API | Catalogue authentication | Licence status | Current limitation |
|---|---|---|---|---|---|
| National Grid Electricity Distribution | https://connecteddata.nationalgrid.co.uk | `https://connecteddata.nationalgrid.co.uk/api/3/action` (CKAN) | None observed | Verify per dataset; many catalogue entries do not declare a licence | Dataset identifiers, resource licences, and schemas need contract tests |
| SP Energy Networks | https://spenergynetworks.opendatasoft.com | `https://spenergynetworks.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset; some catalogue entries do not declare a licence | Record visibility, resource coverage, and update schedules vary |
| SP Electricity North West | https://electricitynorthwest.opendatasoft.com | `https://electricitynorthwest.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Record visibility and download conditions vary by resource |
| Scottish and Southern Electricity Networks | https://data.ssen.co.uk | `https://data-api.ssen.co.uk/api/3/action` (CKAN) | None observed | Verify per dataset | Resource formats, history, and schemas vary |
| UK Power Networks | https://ukpowernetworks.opendatasoft.com | `https://ukpowernetworks.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Some datasets publish metadata or attachments without public record queries |
| Northern Powergrid | https://northernpowergrid.opendatasoft.com | `https://northernpowergrid.opendatasoft.com/api/explore/v2.1` | None observed | Verify per dataset | Some network asset datasets have separate access-request conditions |
| National Energy System Operator | https://www.neso.energy/data-portal | `https://api.neso.energy/api/3/action` (CKAN) | None observed; an account is optional for subscriptions and favourites | Verify per dataset; the current catalogue names the NESO Open Data Licence | National and transmission-system data is context, not a substitute for DSO outage or local-flexibility evidence |

Anonymous catalogue access does not prove that every dataset resource is
anonymous or redistributable. The repository stores curated catalogue metadata
only. Downloaded portal responses, caches, generated inventories, and databases
are local artifacts and must not be committed.
