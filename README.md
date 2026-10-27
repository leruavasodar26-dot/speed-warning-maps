# Speed Warning map files

Ready-made offline map files for the Speed Warning Android app: roads, speed limits and school grounds only,
cut into 2 km squares from the Geofabrik Australia OpenStreetMap extract.

* `index.json` – list of files (name, area, size, date, sha256, URL). The app reads it to offer downloads and updates.
* Files are attached to the `maps-YYYY-MM-DD` releases.
* `rebuild.sh` – downloads the extract, cuts every file, publishes a new release and updates `index.json`
  (run every two months). `build_maps.py` does the cutting; add a new area to `specs` in `main()`.

Current files: **Far North Queensland** (Cooktown – Cairns – Tablelands – Chillagoe – Innisfail – Tully – Cardwell) and
**Townsville – Rockhampton** (Bruce Hwy corridor from Cardwell, about 12 km each side, plus Townsville, Mackay and Rockhampton).

Map data © OpenStreetMap contributors, available under the Open Database License (ODbL).
