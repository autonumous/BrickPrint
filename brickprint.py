#!/usr/bin/env python3
"""
brickprint.py - BrickPrint: LEGO set or LDraw model -> printable STL / 3MF files.

Two ways to run it:

  A) From a set number (parts list comes from Rebrickable):
       export REBRICKABLE_KEY=your_api_key        # free at rebrickable.com
       python3 brickprint.py 75192-1
       python3 brickprint.py 42233 --3mf

  B) From an LDraw model file (.mpd / .ldr), e.g. from omr.ldraw.org:
       python3 brickprint.py 75033-1.mpd
       python3 brickprint.py 75033-1.mpd --3mf --by-colour --bed 256 256
     This also writes assembled.stl: every part in its modelled position.

  Either way, add --instructions to also download the official LEGO building
  instruction PDFs, or use --instructions-only to download just those:
       python3 brickprint.py 42233 --instructions-only

Outputs (in --out, default: the set number or model name):
    <part>.stl         one STL per unique part (studs up, flat on the bed)
    manifest.csv       parts, quantities, colours, status
    assembled.stl      whole model (model-file mode only)
    plate_NN.3mf       --3mf: every part instance on bed-sized plate(s), studs up by default
    plate_NN.stl       --plates: same layout as STL
                       (--by-colour makes plate_<colour>_NN files instead)

Units are millimetres. 1.0 = true LEGO size; use --scale for bigger models.
Pure standard library, no pip installs needed.
"""
import argparse, collections, csv, json, math, os, re, struct, sys
import time, urllib.request, zipfile

LDRAW_ZIP_URL = "https://library.ldraw.org/library/updates/complete.zip"
UNOFFICIAL_URL = "https://library.ldraw.org/library/unofficial/ldrawunf.zip"
CACHE = "ldraw_cache"
LDU_TO_MM = 0.4
API = "https://rebrickable.com/api/v3/lego/sets/{}/parts/?page_size=1000&inc_part_details=1"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


# ======================= downloads / LDraw library =======================
def download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req) as r, open(dest + ".part", "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(dest + ".part", dest)


INSTR_URL = "https://www.lego.com/{locale}/service/building-instructions/{num}"
PDF_RE = re.compile(r"(?:https://www\.lego\.com)?/cdn/product-assets/product\.bi\.core\.pdf/\d+\.pdf")


def set_number(text):
    """'75192-1', '42233', '75033-1.mpd' -> '75192', '42233', '75033'."""
    m = re.search(r"(\d{4,7})(?:-\d+)?", os.path.basename(text))
    return m.group(1) if m else None


def get_instructions(num, locale, dest):
    """Download the official building-instruction PDFs listed on lego.com for a set."""
    page = INSTR_URL.format(locale=locale, num=num)
    print(f"Looking up building instructions for {num}...")
    try:
        req = urllib.request.Request(page, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Could not fetch the instructions page ({e}).\nOpen it in a browser: {page}")
        return 0
    html = html.replace("\\/", "/")
    links = []
    for u in PDF_RE.findall(html):
        u = u if u.startswith("http") else "https://www.lego.com" + u
        if u not in links:
            links.append(u)
    if not links:
        print(f"No instruction PDFs found on the page. Try it in a browser: {page}")
        return 0
    os.makedirs(dest, exist_ok=True)
    got = 0
    for i, url in enumerate(links, 1):
        path = os.path.join(dest, f"{num}_instructions_{i:02d}_of_{len(links):02d}.pdf")
        if os.path.exists(path):
            print(f"  {os.path.basename(path)} already downloaded")
            got += 1
            continue
        try:
            download(url, path)
            got += 1
            print(f"  {os.path.basename(path)}")
        except Exception as e:
            print(f"  failed: {url} ({e})")
        time.sleep(1)  # be polite
    print(f"{got}/{len(links)} instruction PDF(s) in ./{dest}")
    return got


def ensure_ldraw():
    root = os.path.join(CACHE, "ldraw")
    if os.path.isdir(root):
        return root
    os.makedirs(CACHE, exist_ok=True)
    zpath = os.path.join(CACHE, "complete.zip")
    if not os.path.exists(zpath):
        print("Downloading LDraw library (~80 MB, one time)...")
        try:
            download(LDRAW_ZIP_URL, zpath)
        except Exception as e:
            sys.exit(f"Download failed ({e}).\nDownload {LDRAW_ZIP_URL} in your "
                     f"browser and save it as {zpath}, then rerun.")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(CACHE)
    return root


def ensure_unofficial():
    """Unofficial parts (newer / not yet approved). Returns a folder or None."""
    dest = os.path.join(CACHE, "unofficial")
    zpath = os.path.join(CACHE, "ldrawunf.zip")
    try:
        if not os.path.isdir(dest):
            os.makedirs(CACHE, exist_ok=True)
            if not os.path.exists(zpath):
                print("Downloading unofficial LDraw parts...")
                download(UNOFFICIAL_URL, zpath)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(dest)
    except Exception as e:
        print(f"Warning: could not get unofficial parts ({e}); continuing without.")
        return None
    inner = os.path.join(dest, "ldraw")
    return inner if os.path.isdir(inner) else dest


def norm(name):
    return name.replace("\\", "/").lower()


def apply(m, t, p):
    return (m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + t[0],
            m[3] * p[0] + m[4] * p[1] + m[5] * p[2] + t[1],
            m[6] * p[0] + m[7] * p[1] + m[8] * p[2] + t[2])


def mat_mul(a, b):
    return tuple(sum(a[r * 3 + k] * b[k * 3 + c] for k in range(3))
                 for r in range(3) for c in range(3))


def det3(m):
    return (m[0] * (m[4] * m[8] - m[5] * m[7])
            - m[1] * (m[3] * m[8] - m[5] * m[6])
            + m[2] * (m[3] * m[7] - m[4] * m[6]))


class Library:
    def __init__(self, root):
        self.index = {}
        self.parsed = {}
        self.tri_cache = {}
        self.add_root(root)

    def add_root(self, root):
        # official files are added first and win; later roots only fill gaps
        for sub in ("parts", "p"):
            base = os.path.join(root, sub)
            for dp, _, files in os.walk(base):
                for f in files:
                    rel = os.path.relpath(os.path.join(dp, f), base)
                    self.index.setdefault(rel.replace("\\", "/").lower(),
                                          os.path.join(dp, f))

    def find(self, name):
        return self.index.get(norm(name))

    def title(self, name):
        path = self.find(name)
        if not path:
            return ""
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                first = fh.readline().strip()
            return first[2:].strip() if first.startswith("0 ") else ""
        except OSError:
            return ""

    def parse(self, name):
        if name in self.parsed:
            return self.parsed[name]
        path = self.find(name)
        if not path:
            self.parsed[name] = None
            return None
        elems, cw, invnext = [], False, False
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                t = line.split()
                if not t:
                    continue
                if t[0] == "0":
                    if t[1:3] == ["BFC", "INVERTNEXT"]:
                        invnext = True
                    elif t[1:2] == ["BFC"] and "CW" in t[2:]:
                        cw = True
                    elif t[1:2] == ["BFC"] and "CCW" in t[2:]:
                        cw = False
                elif t[0] == "1" and len(t) >= 15:
                    m = [float(v) for v in t[5:14]]
                    elems.append(("ref", t[14], tuple(float(v) for v in t[2:5]), m, invnext))
                    invnext = False
                elif t[0] == "3" and len(t) >= 11:
                    v = [float(x) for x in t[2:11]]
                    elems.append(("tri", [v[0:3], v[3:6], v[6:9]]))
                elif t[0] == "4" and len(t) >= 14:
                    v = [float(x) for x in t[2:14]]
                    q = [v[0:3], v[3:6], v[6:9], v[9:12]]
                    elems.append(("tri", [q[0], q[1], q[2]]))
                    elems.append(("tri", [q[0], q[2], q[3]]))
        self.parsed[name] = (elems, cw)
        return self.parsed[name]

    def triangles(self, name, invert=False, depth=0):
        """Triangles of a file in its local LDraw coordinates, winding resolved."""
        key = (norm(name), invert)
        if key in self.tri_cache:
            return self.tri_cache[key]
        parsed = self.parse(name)
        out = []
        if parsed and depth < 30:
            elems, file_cw = parsed
            flip = file_cw != invert
            for e in elems:
                if e[0] == "tri":
                    a, b, c = e[1]
                    out.append((a, c, b) if flip else (a, b, c))
                else:
                    _, sub, t, m, invnext = e
                    child_inv = invert ^ (det3(m) < 0) ^ invnext
                    for tri in self.triangles(sub, child_inv, depth + 1):
                        out.append(tuple(apply(m, t, p) for p in tri))
        self.tri_cache[key] = out
        return out


# ======================= source A: Rebrickable set =======================
def fetch_parts(set_num, key, include_spares):
    if "-" not in set_num:
        set_num += "-1"
    url = API.format(set_num)
    parts = {}
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"key {key}"})
        with urllib.request.urlopen(req) as r:
            data = json.load(r)
        for row in data["results"]:
            if row["is_spare"] and not include_spares:
                continue
            p = row["part"]
            ids = list((p.get("external_ids") or {}).get("LDraw") or [])
            cands = []
            for c in ids + [p["part_num"], p.get("print_of")]:
                if c and c not in cands:
                    cands.append(c)
            entry = parts.setdefault(p["part_num"], {
                "part_num": p["part_num"], "name": p["name"],
                "candidates": cands, "url": p.get("part_url") or "",
                "qty": 0, "colors": {}})
            entry["qty"] += row["quantity"]
            c = row["color"]["name"]
            entry["colors"][c] = entry["colors"].get(c, 0) + row["quantity"]
        url = data.get("next")
    return list(parts.values())


# ======================= source B: LDraw model file =======================
def read_model(path):
    """Returns (files, main). files[name] = {'refs': [...], 'geom': n}."""
    files, cur, main = {}, None, None
    invnext = False
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            t = line.split()
            if not t:
                continue
            if t[0] == "0" and len(t) >= 3 and t[1] == "FILE":
                cur = norm(" ".join(t[2:]))
                files[cur] = {"refs": [], "geom": 0}
                main = main or cur
                invnext = False
                continue
            if t[0] == "0" and len(t) >= 2 and t[1] == "NOFILE":
                cur = None
                continue
            if cur is None:  # plain .ldr without FILE headers
                cur = main = norm(os.path.basename(path))
                files[cur] = {"refs": [], "geom": 0}
            if t[0] == "0":
                if t[1:3] == ["BFC", "INVERTNEXT"]:
                    invnext = True
            elif t[0] == "1" and len(t) >= 15:
                m = tuple(float(v) for v in t[5:14])
                files[cur]["refs"].append((int(t[1]), tuple(float(v) for v in t[2:5]),
                                           m, norm(" ".join(t[14:])), invnext))
                invnext = False
            elif t[0] in ("3", "4"):
                files[cur]["geom"] += 1
    return files, main


def flatten(files, name, M, T, colour, inv, out, depth=0):
    """Collect every part instance: (part file, colour, matrix, translation, invert)."""
    if depth > 40:
        return
    for col, t, m, sub, invnext in files[name]["refs"]:
        c = colour if col == 16 else col
        W = mat_mul(M, m)
        Tw = tuple(a + b for a, b in zip(apply(M, (0, 0, 0), t), T))
        child_inv = inv ^ (det3(m) < 0) ^ invnext
        if sub in files:
            if files[sub]["geom"] and not files[sub]["refs"]:
                print(f"  warning: embedded geometry part '{sub}' skipped")
                continue
            flatten(files, sub, W, Tw, c, child_inv, out, depth + 1)
        else:
            out.append((sub, c, W, Tw, child_inv))


def inventory_from_model(path, lib):
    files, main = read_model(path)
    if not main:
        sys.exit("No model found in file.")
    instances = []
    flatten(files, main, (1, 0, 0, 0, 1, 0, 0, 0, 1), (0.0, 0.0, 0.0), 16, False, instances)
    parts = {}
    for part, colour, _, _, _ in instances:
        stem = part[:-4] if part.endswith(".dat") else part
        e = parts.setdefault(stem, {
            "part_num": stem.replace("/", "_"), "name": lib.title(part),
            "candidates": [stem], "url": "", "qty": 0, "colors": {}})
        e["qty"] += 1
        label = f"LDraw colour {colour}"
        e["colors"][label] = e["colors"].get(label, 0) + 1
    return list(parts.values()), instances


# ======================= geometry -> print space =======================
def to_mm(p, k):
    # LDraw (-Y up) -> printer (+Z up); a proper rotation, so winding is kept
    return (p[0] * k, p[2] * k, -p[1] * k)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


# Six rotations, each putting a different face of the part on the bed.
ROTATIONS = [
    ("as modelled", lambda x, y, z: (x, y, z)),
    ("flipped", lambda x, y, z: (x, -y, -z)),
    ("on side (+X down)", lambda x, y, z: (z, y, -x)),
    ("on side (-X down)", lambda x, y, z: (-z, y, x)),
    ("on side (+Y down)", lambda x, y, z: (x, z, -y)),
    ("on side (-Y down)", lambda x, y, z: (x, -z, y)),
]


def _score(pts):
    """Lower is better: little overhanging area, big flat contact, low height."""
    zs = [p[2] for t in pts for p in t]
    zmin, zmax = min(zs), max(zs)
    contact = overhang = 0.0
    for a, b, c in pts:
        n = _cross(_sub(b, a), _sub(c, a))
        ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
        if ln < 1e-9:
            continue
        area, nz = ln / 2, n[2] / ln
        if max(a[2], b[2], c[2]) <= zmin + 0.05:
            if nz < -0.99:
                contact += area          # flat face resting on the bed
        elif nz < -0.707:
            overhang += area             # faces down more than 45 degrees: needs support
    return overhang - 0.3 * contact + 0.05 * (zmax - zmin)


def orient_for_printing(tris, mode, k):
    """LDraw triangles -> (mm triangles, label, w, d, h), flat on the bed, min corner at 0,0,0.
    mode: 'up' = as modelled (studs up), 'flip' = upside down, 'auto' = best-scoring face."""
    base = [tuple(to_mm(p, k) for p in t) for t in tris]
    best, best_label, best_score = base, ROTATIONS[0][0], None
    candidates = {"up": ROTATIONS[:1], "flip": ROTATIONS[1:2]}.get(mode, ROTATIONS)
    for label, rot in candidates:
        pts = [tuple(rot(*p) for p in t) for t in base]
        s = _score(pts)
        if best_score is None or s < best_score - 1e-9:
            best, best_label, best_score = pts, label, s

    def extent(ts):
        ps = [p for t in ts for p in t]
        return [(min(p[i] for p in ps), max(p[i] for p in ps)) for i in range(3)]

    ex = extent(best)
    if ex[0][1] - ex[0][0] < ex[1][1] - ex[1][0]:     # long side along X
        best = [tuple((y, -x, z) for (x, y, z) in t) for t in best]
        ex = extent(best)
    best = [tuple((x - ex[0][0], y - ex[1][0], z - ex[2][0]) for (x, y, z) in t) for t in best]
    return best, best_label, ex[0][1] - ex[0][0], ex[1][1] - ex[1][0], ex[2][1] - ex[2][0]


# ======================= writers =======================
def write_stl(path, tris_iter, count):
    """Binary STL from triangles already in mm."""
    with open(path, "wb") as f:
        f.write(b"brickprint".ljust(80, b"\0"))
        f.write(struct.pack("<I", count))
        for a, b, c in tris_iter:
            n = _cross(_sub(b, a), _sub(c, a))
            ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
            f.write(struct.pack("<12fH", n[0] / ln, n[1] / ln, n[2] / ln, *a, *b, *c, 0))


def mesh_indices(tris):
    index, verts, out = {}, [], []
    for t in tris:
        ids = []
        for p in t:
            key = (round(p[0], 4), round(p[1], 4), round(p[2], 4))
            if key not in index:
                index[key] = len(verts)
                verts.append(key)
            ids.append(index[key])
        if len(set(ids)) == 3:
            out.append(tuple(ids))
    return verts, out


def write_3mf(path, plate, objects):
    """plate: [(item, x, y)], objects: part -> (verts, tris, name). One mesh per part type."""
    from xml.sax.saxutils import quoteattr
    ids, res, build = {}, [], []
    for it, x, y in plate:
        part = it["part"]
        if part not in ids:
            ids[part] = len(ids) + 1
            verts, tris, name = objects[part]
            v = "".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in verts)
            t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
            res.append(f'<object id="{ids[part]}" type="model" name={quoteattr(name)}>'
                       f'<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>')
        build.append(f'<item objectid="{ids[part]}" '
                     f'transform="1 0 0 0 1 0 0 0 1 {x:.4f} {y:.4f} 0"/>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources>{"".join(res)}</resources><build>{"".join(build)}</build></model>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
             '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)


def shelf_pack(items, bed_w, bed_d, gap):
    plates, cur = [], []
    x = y = row_h = 0.0
    for it in sorted(items, key=lambda i: -i["d"]):
        w, d = it["w"], it["d"]
        if w > bed_w or d > bed_d:
            print(f"  warning: {it['part']} ({w:.0f} x {d:.0f} mm) is larger than the bed; own plate")
            plates.append([(it, 0.0, 0.0)])
            continue
        if x + w > bed_w:
            x, y, row_h = 0.0, y + row_h + gap, 0.0
        if y + d > bed_d:
            plates.append(cur)
            cur, x, y, row_h = [], 0.0, 0.0, 0.0
        cur.append((it, x, y))
        x += w + gap
        row_h = max(row_h, d)
    if cur:
        plates.append(cur)
    return plates


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower() or "x"


def build_plates(out_dir, parts, geo, args, k):
    objects, items = {}, []
    print("\nChoosing print orientations (default: %s)..." % args.orient)
    for p in parts:
        g = geo.get(p["part_num"])
        if not g:
            continue
        mode = args.orient_part.get(p["part_num"], args.orient)
        pts, label, w, d, h = orient_for_printing(g, mode, k)
        objects[p["part_num"]] = {"pts": pts,
                                  "name": f"{p['part_num']} {p['name']}".strip()}
        print(f"  {p['part_num']:>10}: {label}, {w:.1f} x {d:.1f} x {h:.1f} mm")
        for colour, n in p["colors"].items():
            items += [{"part": p["part_num"], "w": w, "d": d, "colour": colour}] * n

    groups = collections.defaultdict(list)
    for it in items:
        groups[it["colour"] if args.by_colour else None].append(it)

    meshes = {}
    if args.three_mf:
        meshes = {n: mesh_indices(o["pts"]) + (o["name"],) for n, o in objects.items()}

    written = 0
    for colour, grp in sorted(groups.items(), key=lambda kv: str(kv[0])):
        for i, plate in enumerate(shelf_pack(grp, args.bed[0], args.bed[1], args.gap), 1):
            tag = f"{i:02d}" if colour is None else f"{slug(colour)}_{i:02d}"
            if args.three_mf:
                write_3mf(os.path.join(out_dir, f"plate_{tag}.3mf"), plate, meshes)
                written += 1
                print(f"plate_{tag}.3mf: {len(plate)} parts")
            if args.plates:
                def gen():
                    for it, px, py in plate:
                        for a, b, c in objects[it["part"]]["pts"]:
                            yield tuple((x + px, y + py, z) for (x, y, z) in (a, b, c))
                count = sum(len(objects[it["part"]]["pts"]) for it, _, _ in plate)
                write_stl(os.path.join(out_dir, f"plate_{tag}.stl"), gen(), count)
                written += 1
                print(f"plate_{tag}.stl: {len(plate)} parts")
    return written


# ======================= main =======================
def main():
    ap = argparse.ArgumentParser(
        description="LEGO set number or LDraw model file -> STL / 3MF for 3D printing.")
    ap.add_argument("source", help="set number (e.g. 75192-1) or an LDraw .mpd/.ldr file")
    ap.add_argument("--out", default=None, help="output folder")
    ap.add_argument("--3mf", dest="three_mf", action="store_true",
                    help="write 3MF build plate(s) with every part instance")
    ap.add_argument("--plates", action="store_true", help="write the same plates as STL files")
    ap.add_argument("--by-colour", action="store_true", help="separate plates per colour")
    ap.add_argument("--bed", nargs=2, type=float, default=[220, 220], metavar=("W", "D"),
                    help="bed size in mm (default 220 220)")
    ap.add_argument("--gap", type=float, default=3.0, help="space between parts, mm")
    ap.add_argument("--orient", choices=["up", "auto"], default="up",
                    help="plate orientation: 'up' = as modelled, studs up (default); "
                         "'auto' = pick the face that needs the least support")
    ap.add_argument("--orient-part", action="append", default=[], metavar="PART=MODE",
                    help="override one part, MODE is up, flip or auto (repeatable), "
                         "e.g. --orient-part 3705=auto --orient-part 3034=flip")
    ap.add_argument("--keep-orientation", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--scale", type=float, default=1.0, help="1.0 = true LEGO size")
    ap.add_argument("--include-spares", action="store_true", help="set mode: include spare parts")
    ap.add_argument("--no-assembly", action="store_true", help="model mode: skip assembled.stl")
    ap.add_argument("--no-part-stl", action="store_true", help="skip the per-part STL files")
    ap.add_argument("--instructions", action="store_true",
                    help="also download the official LEGO building instruction PDFs")
    ap.add_argument("--instructions-only", action="store_true",
                    help="download only the instruction PDFs, nothing else")
    ap.add_argument("--locale", default="en-gb", help="lego.com locale for instructions (default en-gb)")
    ap.add_argument("--ldraw", default=None, help="use an existing ldraw folder, no downloads")
    args = ap.parse_args()

    k = LDU_TO_MM * args.scale
    if args.keep_orientation:
        args.orient = "up"
    overrides = {}
    for spec in args.orient_part:
        part, _, mode = spec.partition("=")
        if mode not in ("up", "flip", "auto"):
            sys.exit(f"--orient-part {spec!r}: use PART=up, PART=flip or PART=auto")
        overrides[part] = mode
    args.orient_part = overrides
    src = args.source
    is_model = os.path.isfile(src)
    if not is_model and src.lower().endswith((".mpd", ".ldr", ".dat")):
        sys.exit(f"File not found: {src}")

    key = os.environ.get("REBRICKABLE_KEY")
    if not is_model and not key and not args.instructions_only:
        sys.exit("Set REBRICKABLE_KEY first (free key from rebrickable.com),\n"
                 "or pass an LDraw .mpd/.ldr file instead of a set number.")

    out_dir = args.out or (os.path.splitext(os.path.basename(src))[0] if is_model else src)
    os.makedirs(out_dir, exist_ok=True)

    if args.instructions or args.instructions_only:
        num = set_number(src)
        if num:
            get_instructions(num, args.locale, os.path.join(out_dir, "instructions"))
        else:
            print("Could not work out a set number from the input, skipping instructions.")
        if args.instructions_only:
            return

    lib = Library(args.ldraw or ensure_ldraw())
    if not args.ldraw:
        unof = ensure_unofficial()
        if unof:
            lib.add_root(unof)

    instances = []
    if is_model:
        parts, instances = inventory_from_model(src, lib)
        print(f"{len(instances)} part instances, {len(parts)} distinct parts")
    else:
        print("Fetching part list...")
        parts = fetch_parts(src, key, args.include_spares)
        print(f"{len(parts)} unique parts, {sum(p['qty'] for p in parts)} total pieces")

    # ---- per-part geometry, STLs and manifest ----
    rows, missing, geo = [], [], {}
    for i, p in enumerate(parts, 1):
        tris, used = [], None
        for cand in p["candidates"]:
            tris = lib.triangles(f"{cand}.dat")
            if tris:
                used = cand
                break
        if tris:
            geo[p["part_num"]] = tris
            if not args.no_part_stl:
                pts = orient_for_printing(tris, "up", k)[0]
                write_stl(os.path.join(out_dir, f"{p['part_num']}.stl"), pts, len(pts))
            status = "ok" if used == p["candidates"][0] or used == p["part_num"] \
                else f"ok (via {used})"
        else:
            status = "missing in LDraw"
            missing.append(p)
        print(f"[{i}/{len(parts)}] {p['part_num']:>12}  x{p['qty']:<4} {status}")
        rows.append([p["part_num"], used or "", p["name"], p["qty"],
                     "; ".join(f"{c} x{n}" for c, n in p["colors"].items()),
                     status, p["url"], ", ".join(p["candidates"])])

    with open(os.path.join(out_dir, "manifest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["part_num", "ldraw_id", "name", "quantity", "colours",
                    "status", "rebrickable_url", "ids_tried"])
        w.writerows(rows)

    # ---- assembled model (model mode only) ----
    if is_model and not args.no_assembly:
        asm = []
        for part, colour, W, Tw, inv in instances:
            for tri in lib.triangles(part, inv):
                asm.append(tuple(to_mm(apply(W, Tw, p), k) for p in tri))
        if asm:
            ps = [p for t in asm for p in t]
            lo = [min(p[i] for p in ps) for i in range(3)]
            hi = [max(p[i] for p in ps) for i in range(3)]
            shifted = (tuple((x - lo[0], y - lo[1], z - lo[2]) for (x, y, z) in t) for t in asm)
            write_stl(os.path.join(out_dir, "assembled.stl"), shifted, len(asm))
            print(f"\nassembled.stl: {hi[0]-lo[0]:.0f} x {hi[1]-lo[1]:.0f} x {hi[2]-lo[2]:.0f} mm")

    # ---- build plates ----
    n_plates = 0
    if args.three_mf or args.plates:
        n_plates = build_plates(out_dir, parts, geo, args, k)

    if missing:
        print("\nNo geometry found for these parts (not printed):")
        for p in missing:
            print(f"  {p['part_num']}  x{p['qty']}  {p['name']}")
            print(f"      tried: {', '.join(p['candidates'])}   {p['url']}")

    print(f"\nDone. Output is in ./{out_dir}" + (f" ({n_plates} plate file(s))" if n_plates else ""))


if __name__ == "__main__":
    main()
