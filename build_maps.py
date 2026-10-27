#!/usr/bin/env python3
"""Speed Warning map files: cut roads + speed limits + schools from the Geofabrik Australia extract
into 2 km squares (same format as the app's TileCodec v2), one zip per area, plus index.json.
Each road: [id, highway, limit, name, ref, school 0/1, [lat,lon,...]] and, since Speed Warning 1.6, a trailing 1 = roundabout
(OSM junction=roundabout or junction=circular). Older apps ignore the extra item; 1.6 treats a missing one as "not a roundabout".
Usage: build_maps.py <roads.pbf> <outdir> <date YYYY-MM-DD> <base_url>"""
import sys, os, json, math, re, zipfile, hashlib, collections
import osmium

ROADS = set("motorway trunk primary secondary tertiary unclassified residential living_street road busway "
            "motorway_link trunk_link primary_link secondary_link tertiary_link".split())
SIZE = 0.02          # Tiles.SIZE_DEG in the app
MARGIN_M = 40.0      # TileCodec.split margin
KY = 110540.0
def kx(lat): return 111320.0 * math.cos(math.radians(lat))
def key(lat, lon): return (math.floor(lat / SIZE), math.floor(lon / SIZE))
def around(lat, lon, m):
    dl = m / KY; dn = m / kx(lat)
    return {key(lat + a, lon + b) for a in (-dl, 0, dl) for b in (-dn, 0, dn)}
def metres(a, b, c, d): return math.hypot((d - b) * kx(a), (c - a) * KY)

def parse_limit(v):
    if not v: return None
    s = v.strip().lower()
    if s == "au:urban": return 50
    if s == "au:rural": return 100
    m = re.search(r"\d+", s)
    if not m: return None
    n = int(m.group())
    return round(n * 1.609) if "mph" in s else n

class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.ways = []; self.schools = []
    def node(self, n):
        if n.tags.get("amenity") == "school" and n.location.valid():
            self.schools.append([[(round(n.location.lat, 6), round(n.location.lon, 6))]])
    def way(self, w):
        t = w.tags; hw = t.get("highway")
        if hw not in ROADS: return
        try: pts = [(round(n.lat, 6), round(n.lon, 6)) for n in w.nodes if n.location.valid()]
        except osmium.InvalidLocationError: return
        if len(pts) < 1: return
        ms = t.get("maxspeed") or t.get("maxspeed:forward")
        cond = (t.get("maxspeed:conditional") or "").lower()
        school = ("school" in cond or "40 @" in cond or "school_zone" in t or t.get("hazard") == "school_zone"
                  or "school" in (t.get("zone:maxspeed") or "").lower())
        rb = (t.get("junction") or "").strip().lower() in ("roundabout", "circular")
        self.ways.append((w.id, hw, parse_limit(ms), t.get("name"), t.get("ref"), 1 if school else 0, pts, 1 if rb else 0))
    def area(self, a):
        if a.tags.get("amenity") != "school": return
        rings = []
        for outer in a.outer_rings():
            rings.append([(round(n.lat, 6), round(n.lon, 6)) for n in outer])
        if rings: self.schools.append(rings)

def bruce_points(ways, s_lat, n_lat):
    out = []
    for (_id, hw, _l, name, ref, _s, pts, _rb) in ways:
        refs = [r.strip().upper().replace(" ", "") for r in (ref or "").split(";")]
        if (name == "Bruce Highway" or "A1" in refs) and hw in ("motorway", "trunk", "primary", "motorway_link", "trunk_link"):
            for p in pts:
                if s_lat <= p[0] <= n_lat: out.append(p)
    return out

def cover_box(s, w, n, e):
    a = key(s, w); b = key(n - 1e-9, e - 1e-9)
    return {(y, x) for y in range(a[0], b[0] + 1) for x in range(a[1], b[1] + 1)}

def cover_near(points, km):
    out = set()
    for (la, lo) in points:
        dl = km * 1000 / KY; dn = km * 1000 / kx(la)
        a = key(la - dl, lo - dn); b = key(la + dl, lo + dn)
        for y in range(a[0], b[0] + 1):
            for x in range(a[1], b[1] + 1):
                # tile centre within km (+ half a tile) of the point
                cy = (y + 0.5) * SIZE; cx = (x + 0.5) * SIZE
                if metres(la, lo, cy, cx) <= km * 1000 + 1500: out.add((y, x))
    return out

def thin(points, m=500.0):
    out = []; last = None
    for p in points:
        if last is None or metres(last[0], last[1], p[0], p[1]) >= m: out.append(p); last = p
    return out

def r6(v): return round(v, 6)

def build_file(fid, ways, schools, cover):
    tw = collections.defaultdict(dict); ts = collections.defaultdict(list)
    for wy in ways:
        pts = wy[6]; hit = set()
        if len(pts) == 1: hit |= around(pts[0][0], pts[0][1], MARGIN_M)
        for i in range(len(pts) - 1):
            a = pts[i]; b = pts[i + 1]
            n = int(metres(a[0], a[1], b[0], b[1]) / 50.0) + 1
            for s in range(n + 1):
                f = s / n
                hit |= around(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, MARGIN_M)
        for k in hit:
            if k in cover: tw[k][wy[0]] = wy
    for sc in schools:
        hit = set()
        for r in sc:
            for p in r:
                hit |= around(p[0], p[1], MARGIN_M); hit |= around(p[0], p[1], 200.0)
        for k in hit:
            if k in cover: ts[k].append(sc)
    rbs = {w[0] for k in tw for w in tw[k].values() if w[7]}
    tiles = {}
    for k in set(tw) | set(ts):
        wsj = [[w[0], w[1], w[2], w[3], w[4], w[5], [c for p in w[6] for c in p]] + ([1] if w[7] else []) for w in tw[k].values()]
        ssj = [[[c for p in r for c in p] for r in sc] for sc in ts[k]]
        tiles[k] = json.dumps({"v": 2, "ways": wsj, "schools": ssj}, separators=(",", ":"), ensure_ascii=False)
    return tiles, len(rbs)

def runs(cover):
    rows = collections.defaultdict(list)
    for (y, x) in cover: rows[y].append(x)
    out = []
    for y in sorted(rows):
        xs = sorted(rows[y]); start = prev = xs[0]
        for x in xs[1:]:
            if x == prev + 1: prev = x; continue
            out.append([y, start, prev]); start = prev = x
        out.append([y, start, prev])
    return out

def main():
    pbf, outdir, date, base = sys.argv[1:5]
    os.makedirs(outdir, exist_ok=True)
    h = H(); h.apply_file(pbf, locations=True)
    print("ways", len(h.ways), "roundabout pieces", sum(1 for w in h.ways if w[7]), "schools", len(h.schools), flush=True)
    files = []
    # File 1: Far North Queensland – Cooktown (N) to Cardwell (S), west to Chillagoe
    fnq = cover_box(-18.36, 144.40, -15.30, 146.40)
    # File 2: Bruce Hwy corridor (12 km each side) Cardwell -> Rockhampton + Townsville, Mackay, Rockhampton urban areas
    bp = thin(bruce_points(h.ways, -23.45, -18.20))
    print("bruce points", len(bp), flush=True)
    tr = cover_near(bp, 12.0)
    tr |= cover_near([(-19.27, 146.78)], 20.0)   # Townsville + Thuringowa
    tr |= cover_near([(-21.14, 149.17)], 15.0)   # Mackay
    tr |= cover_near([(-23.37, 150.51)], 15.0)   # Rockhampton
    specs = [("fnq", "Far North Queensland", "Cooktown – Cairns – Tablelands – Chillagoe – Innisfail – Tully – Cardwell", fnq),
             ("townsville-rockhampton", "Townsville – Rockhampton", "Bruce Hwy from Cardwell via Ingham, Townsville, Bowen, Mackay and Sarina to Rockhampton (about 12 km each side, plus Townsville, Mackay and Rockhampton)", tr)]
    for fid, name, area, cover in specs:
        tiles, n_rb = build_file(fid, h.ways, h.schools, cover)
        ys = [k[0] for k in cover]; xs = [k[1] for k in cover]
        bbox = [r6(min(ys) * SIZE), r6(min(xs) * SIZE), r6((max(ys) + 1) * SIZE), r6((max(xs) + 1) * SIZE)]
        meta = {"v": 1, "id": fid, "name": name, "area": area, "date": date, "bbox": bbox, "cover": runs(cover)}
        zp = os.path.join(outdir, fid + ".zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr("meta.json", json.dumps(meta, separators=(",", ":"), ensure_ascii=False))
            for (y, x), body in sorted(tiles.items()):
                z.writestr(f"t_{y}_{x}.json", body)
        data = open(zp, "rb").read()
        raw = sum(len(b.encode()) for b in tiles.values())
        files.append({"id": fid, "name": name, "area": area, "date": date, "bytes": len(data), "unpacked": raw,
                      "sha256": hashlib.sha256(data).hexdigest(), "url": f"{base}/{fid}.zip",
                      "squares": len(cover), "squaresWithRoads": len(tiles), "roundabouts": n_rb, "bbox": bbox})
        print(fid, "squares", len(cover), "with roads", len(tiles), "roundabout pieces", n_rb, "zip", len(data), "unpacked", raw, flush=True)
    idx = {"v": 1, "updated": date, "source": "OpenStreetMap contributors (ODbL), Geofabrik Australia extract", "files": files}
    json.dump(idx, open(os.path.join(outdir, "index.json"), "w"), indent=1, ensure_ascii=False)

if __name__ == "__main__": main()
