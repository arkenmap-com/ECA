#!/usr/bin/env python3
"""Prepare the 48-hour scenario with one ignition at the AOI centre."""

import prepare_aoi_48h_single_point as scenario


scenario.RUN_NAME = "aoi-25m-bcdem-summer-p90-48h-prevailing-single-center"
scenario.LOCATION_SLUG = "center"
scenario.LOCATION_DISPLAY = "central"
scenario.LOCATION_DEFINITION = "centre of the AOI projected bounding box"
scenario.X_FRACTION = 0.5
scenario.Y_FRACTION = 0.5
scenario.RESULTS_DIRNAME = "results-growth"
scenario.RUN = scenario.ROOT / "runs" / scenario.RUN_NAME
scenario.DERIVED = scenario.RUN / "data" / "derived"
scenario.PREPARED = scenario.RUN / "data" / "weather" / "prepared"
scenario.IGNITION = scenario.RUN / "data" / "ignition_single_center.geojson"
scenario.CONFIG = scenario.ROOT / "examples" / f"{scenario.RUN_NAME}.json"


if __name__ == "__main__":
    scenario.main()
