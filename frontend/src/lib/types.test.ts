import type { FlexZone } from "./types";

const FULLY_NULLABLE_ZONE: FlexZone = {
  zone_id: "zone-nullable",
  dso: "TEST",
  platform: null,
  area_name: null,
  zone_type: null,
  postcode_prefixes: [],
  postcodes: [],
  geometry: null,
  source_dataset_id: null,
};

describe("FlexZone", () => {
  it("represents backend nullable fields without omitting them", () => {
    expect(FULLY_NULLABLE_ZONE).toEqual(
      expect.objectContaining({
        platform: null,
        area_name: null,
        zone_type: null,
        geometry: null,
        source_dataset_id: null,
      }),
    );
  });
});
