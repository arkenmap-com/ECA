#!/usr/bin/env bash
set -euo pipefail

# Downloads the May–October 2025 BCWS daily files in four parallel streams and
# retains only Smallwood (404), Slocan (406), and Norns (408).  This is a
# one-season scenario input, not the multi-year long-term weather library.

root="$(cd "$(dirname "$0")" && pwd)"
out="$root/data/bcws-weather"
target="$out/2025_nelson_stations.csv"
temporary="${target}.partial"
scratch="/private/tmp/bcws-2025-daily"
mkdir -p "$out" "$scratch"

if [[ -s "$target" ]]; then
  echo "Using existing $target"
  exit 0
fi

fetch_day() {
  local day="$1"
  curl -sS --fail --ftp-method nocwd \
    "ftp://ftp.for.gov.bc.ca/HPR/external/%21publish/BCWS_DATA_MART/2025/${day}.csv" \
    -o "$scratch/${day}.csv"
}
export -f fetch_day
export scratch

dates=()
day="2025-05-01"
while [[ "$day" != "2025-11-01" ]]; do
  dates+=("$day")
  day="$(date -j -v+1d -f '%Y-%m-%d' "$day" '+%Y-%m-%d')"
done
printf '%s\n' "${dates[@]}" | xargs -n 1 -P 4 bash -c 'fetch_day "$0"'

first=1
for file in "$scratch"/2025-*.csv; do
  awk -F',' -v first="$first" '
    NR == 1 { if (first == 1) print; next }
    $1 == "\"404\"" || $1 == "\"406\"" || $1 == "\"408\"" { print }
  ' "$file"
  first=0
done > "$temporary"
mv "$temporary" "$target"
echo "Created $target"
