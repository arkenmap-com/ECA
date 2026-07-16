# Nelson, BC wildfire-spread pilot

This repository records a small, reproducible **Cell2Fire** trial for the area around Nelson, British Columbia. It is a conditional spread demonstration, not a wildfire forecast or a burn-probability product.

![Conditional Cell2Fire footprint around Nelson](nelson-pilot/nelson-conditional-test.png)

Orange cells show the final four-hour footprint from one deterministic simulation. The base map is the Canadian Forest Fire Danger Rating System (CFFDRS) fuel-type layer.

## What is included

- A roughly 20 × 25 km, 100 m fuel grid around Nelson, sourced from NRCan's CWFIS FBP fuel-type service.
- A 250 m CWFIS elevation raster and derived slope/aspect surfaces.
- `prepare_nelson_pilot.py`, which converts those rasters to a Cell2Fire input instance.
- `render_nelson_map.py`, which overlays the final burned grid on the fuel map.
- An experimental `Dockerfile.burnp3` and `run-burnp3-console.sh` for eventually running the BurnP3+ / SyncroSim workflow on an x86_64 Linux container.

The Cell2Fire source code, compiled executable, virtual environment, and full result directories are intentionally not committed. Obtain Cell2Fire from its upstream project before rerunning the model.

## Recreate the test

1. Clone [Cell2Fire](https://github.com/cell2fire/Cell2Fire) alongside this repository and install its Python requirements. On Apple Silicon, the included local build used C++14, Homebrew Boost/Eigen, and `libomp`.
2. From this repository root, run `python3 prepare_nelson_pilot.py`. It writes `Cell2Fire/data/nelson-pilot/`.
3. From `Cell2Fire/cell2fire`, run the model:

```bash
python main.py \
  --input-instance-folder ../data/nelson-pilot/ \
  --output-folder ../results/nelson-conditional-test \
  --ignitions --sim-years 1 --nsims 1 --finalGrid \
  --weather rows --nweathers 1 --Fire-Period-Length 1.0 \
  --output-messages --ROS-CV 0.0 --seed 20260716 \
  --grids --combine --verbose
```

4. From this repository root, run `python3 render_nelson_map.py` to recreate the PNG.

## Test assumptions and limitations

The test uses one ignition and deliberately severe **synthetic** four-hour weather (not observed or forecast weather), so the result is only a software/data-pipeline check. It burned 72 cells, about 72 ha at 100 m resolution.

For a defensible burn-probability study, use BCWS/observed weather distributions, realistic historical or scenario ignition locations, calibration, sensitivity checks, and thousands of stochastic iterations. Use results for planning and research—not as operational fire prediction.

## Data source

Fuel and elevation inputs were obtained from the Canadian Wildland Fire Information System (CWFIS): [CFFDRS FBP fuel-type data](https://open.canada.ca/data/en/dataset/4e66dd2f-5cd0-42fd-b82c-a430044b31de). The elevation layer is resampled from 250 m resolution; slope and aspect therefore support a pilot only.
