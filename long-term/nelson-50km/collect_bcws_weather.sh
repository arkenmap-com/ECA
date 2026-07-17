#!/usr/bin/env bash
set -euo pipefail

# Streams the province-wide BCWS annual archives and retains only the selected
# local stations (Smallwood, Slocan, Norns) during the May–October fire season.
# It deliberately does not retain the multi-gigabyte source archives.

root="$(cd "$(dirname "$0")" && pwd)"
out="$root/data/bcws-weather"
mkdir -p "$out"

for year in $(seq 2000 2021); do
  target="$out/${year}_nelson_stations.csv"
  if [[ -s "$target" ]]; then
    continue
  fi

  temporary="${target}.partial"
  curl -sS --fail --ftp-method nocwd \
    "ftp://ftp.for.gov.bc.ca/HPR/external/%21publish/BCWS_DATA_MART/${year}/${year}_BCWS_WX_OBS.csv" \
    | awk -F',' '
        NR == 1 { print; next }
        ($1 == "\"404\"" || $1 == "\"406\"" || $1 == "\"408\"") &&
        substr($3, 6, 2) >= "05" && substr($3, 6, 2) <= "10" { print }
      ' > "$temporary"
  mv "$temporary" "$target"
done
