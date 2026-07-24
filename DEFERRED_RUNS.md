# Deferred simulation runs

## 1 km ignition-grid run — not yet authorized to execute

Requested for later:

- Use the existing AOI [area of interest].
- Use ignition points on a 1 km grid, clipped to burnable cells within the AOI.
- Use the official native 30 m FBP [Fire Behaviour Prediction] fuel raster.
- Use the official 30 m MRDEM [Multi-Resolution Digital Elevation Model] DTM [Digital Terrain Model].
- Derive weather from the latest available 10 complete years of Smallwood station summer records.
- Use summer-only weather (June–August).
- Use prevailing summer wind direction, with the method and rationale documented.
- Do not prepare or run this simulation until Alex explicitly approves it.

Questions to confirm before execution:

1. Does “average” mean one internally consistent representative weather day selected near the joint 90th-percentile fire-weather severity, or an hourly composite made by averaging selected severe days? The representative-day method is recommended because averaging weather variables independently can create a physically inconsistent weather sequence.
2. Should “90th percentile” be based on FWI [Fire Weather Index], a multivariable severity score, or separate percentiles for temperature, RH [relative humidity], wind speed, and precipitation? The recommended default is a representative observed day near the summer 90th-percentile FWI.
3. Confirm the simulation duration (for example, 24 or 48 hours).
4. Confirm whether every valid 1 km grid ignition should be simulated or whether a run cap is required.
5. Confirm whether the 10-year window means the latest 10 complete summers available when the run is started.

