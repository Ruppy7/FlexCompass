# Postcode and geometry matching

Postcodes are lookup evidence for public network zones, not authoritative zones
themselves. Resolution proceeds from strongest to weakest evidence:

1. Point-in-polygon when public GeoJSON and postcode coordinates are available.
2. Exact full-postcode membership when a source publishes a postcode list.
3. Outward-code or area-prefix matching when that is the only public evidence.
4. No match when none of the above is supported.

The resolver returns every supported zone match and records match quality. It
must not manufacture a match merely because a postcode is geographically near a
known prefix. Prefix matches can overlap and should be treated as directional.

The checked-in zone seed is empty. Tests use explicit synthetic zones so they do
not promote test fixtures into public-data claims. Future work should add public
postcode coordinates, verified zone geometry, and fixture-based contract tests
for each portal normaliser.
