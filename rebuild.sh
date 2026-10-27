#!/usr/bin/env bash
# Speed Warning map files: download the OSM Australia extract, cut the map files, publish them on GitHub.
# One-line rebuild:  bash /workspace/sw-maps/repo/rebuild.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${SW_MAPS_WORK:-/workspace/sw-maps}
REPO=leruavasodar26-dot/speed-warning-maps
DATE=$(TZ=Australia/Brisbane date +%F)
TAG=maps-$DATE
ROADS=motorway,trunk,primary,secondary,tertiary,unclassified,residential,living_street,road,busway,motorway_link,trunk_link,primary_link,secondary_link,tertiary_link
mkdir -p "$WORK/work"; cd "$WORK/work"

command -v osmium >/dev/null || sudo apt-get install -y osmium-tool
[ -x "$WORK/venv/bin/python" ] || { python3 -m venv "$WORK/venv"; "$WORK/venv/bin/pip" install -q osmium; }

echo "1/5 downloading the Australia extract (about 1 GB)…"
curl -fsSL --retry 5 -o australia-latest.osm.pbf.part https://download.geofabrik.de/australia-oceania/australia-latest.osm.pbf
mv australia-latest.osm.pbf.part australia-latest.osm.pbf

echo "2/5 cutting North Queensland, roads and schools only…"
osmium extract -s complete_ways -b 144.3,-23.7,150.8,-15.2 australia-latest.osm.pbf -o nq.pbf --overwrite
osmium tags-filter nq.pbf "w/highway=$ROADS" nwr/amenity=school -o nq-roads.pbf --overwrite

echo "3/5 making the map files…"
OUT="$WORK/out-$DATE"; rm -rf "$OUT"
"$WORK/venv/bin/python" "$HERE/build_maps.py" nq-roads.pbf "$OUT" "$DATE" "https://github.com/$REPO/releases/download/$TAG"

echo "4/5 publishing release $TAG…"
if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  gh release upload "$TAG" -R "$REPO" --clobber "$OUT"/*.zip "$OUT/index.json"
else
  gh release create "$TAG" -R "$REPO" --latest --title "Map files $DATE" \
    --notes "Speed Warning map files (roads, speed limits, schools). Data © OpenStreetMap contributors, ODbL." \
    "$OUT"/*.zip "$OUT/index.json"
fi
# the app reads index.json from the main branch (and the latest release as a backup)
SHA=$(gh api "repos/$REPO/contents/index.json" --jq .sha 2>/dev/null || true)
B64=$(base64 -w0 "$OUT/index.json")
if [ -n "$SHA" ]; then gh api -X PUT "repos/$REPO/contents/index.json" -f message="Map files $DATE" -f content="$B64" -f sha="$SHA" >/dev/null
else gh api -X PUT "repos/$REPO/contents/index.json" -f message="Map files $DATE" -f content="$B64" >/dev/null; fi

echo "5/5 tidying: keep the 3 newest map releases…"
gh release list -R "$REPO" --limit 50 --json tagName --jq '.[].tagName' | grep '^maps-' | sort -r | tail -n +4 | while read -r old; do
  gh release delete "$old" -R "$REPO" --yes --cleanup-tag
done
# check: every file in the index downloads and matches its sha256
"$WORK/venv/bin/python" - "$OUT/index.json" <<'PY'
import json, sys, hashlib, urllib.request
for f in json.load(open(sys.argv[1]))["files"]:
    d = urllib.request.urlopen(f["url"], timeout=120).read()
    ok = hashlib.sha256(d).hexdigest() == f["sha256"]
    print(("OK  " if ok else "BAD ") + f["id"], len(d), "bytes")
    if not ok: sys.exit(1)
PY
echo "Done: $TAG"
