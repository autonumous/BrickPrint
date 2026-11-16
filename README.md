# BrickPrint

Turn a LEGO set into 3D-printable files.

Give it a **set number** (the parts list comes from [Rebrickable](https://rebrickable.com)) or an **LDraw model file** (`.mpd` / `.ldr`), and it produces:

- one **STL per unique part**, true size, in millimetres
- a **`manifest.csv`** with quantities, colours and status for every part
- an **`assembled.stl`** of the whole model (model-file mode)
- **build plates** with every part instance laid out on your bed, as **3MF** and/or STL
- optionally, the official **LEGO building instruction PDFs**

Part geometry comes from the open [LDraw](https://www.ldraw.org) parts library, which the script downloads and caches on first run. It is a single file, pure Python standard library, with nothing to `pip install`.

> **Status:** proof of concept. It works end to end on the sets it has been tried with, but the geometry is LDraw's visual geometry, **not print-tuned**. Printed parts will not clutch with real LEGO without tolerance adjustments (see [Limitations](#limitations)).

---

## Contents

- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Two ways to run it](#two-ways-to-run-it)
- [Options](#options)
- [Output files](#output-files)
- [Examples](#examples)
- [Part orientation](#part-orientation)
- [How it works](#how-it-works)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Credits and licensing](#credits-and-licensing)

---

## Requirements

- Python 3.8 or newer
- Internet access on first run (LDraw library, about 80 MB, is downloaded once)
- For **set-number mode** only: a free Rebrickable API key

Get a key at [rebrickable.com](https://rebrickable.com) under *Account → Settings → API*, then make it available to the script:

```bash
# macOS / Linux
export REBRICKABLE_KEY=your_api_key

# Windows PowerShell
$env:REBRICKABLE_KEY="your_api_key"

# Windows Command Prompt
set REBRICKABLE_KEY=your_api_key
```

## Quick start

```bash
python3 brickprint.py 42233 --3mf
```

This fetches the parts list for set 42233, converts every part to STL, and writes 3MF build plates with all parts laid out. Results go in a folder named `42233/`.

---

## Two ways to run it

### A) From a set number

```bash
python3 brickprint.py 75192-1
```

The `-1` suffix is added automatically if you leave it off. Quantities come from the Rebrickable inventory. Spare parts are excluded unless you pass `--include-spares`.

### B) From an LDraw model file

```bash
python3 brickprint.py 75033-1.mpd
```

Use this when you have a 3D model of the set, for example from the [LDraw Official Model Repository](https://omr.ldraw.org). In this mode you also get `assembled.stl`, the complete model with every part in its modelled position, and plate colours come from the model's LDraw colour codes.

The script decides which mode to use by checking whether the argument is a file that exists.

---

## Options

```
python3 brickprint.py SOURCE [options]
```

`SOURCE` is a set number (e.g. `75192-1`) or the path to an LDraw `.mpd` / `.ldr` file.

### Output

| Option | Default | Description |
|---|---|---|
| `--out DIR` | set number or model name | Output folder. |
| `--3mf` | off | Write 3MF build plate(s) with every part instance. |
| `--plates` | off | Write the same plates as STL files. |
| `--by-colour` | off | Make separate plates per colour, so you can print one colour at a time. Uses Rebrickable colour names in set mode and LDraw colour codes in model mode. |
| `--no-part-stl` | off | Skip the per-part STL files. |
| `--no-assembly` | off | Model mode: skip `assembled.stl`. |
| `--include-spares` | off | Set mode: include spare parts in the quantities. |

### Plate layout

| Option | Default | Description |
|---|---|---|
| `--bed W D` | `220 220` | Bed size in mm. If everything doesn't fit, extra plates are written (`plate_02`, `plate_03`, ...). |
| `--gap MM` | `3.0` | Spacing between parts on a plate, in mm. |
| `--orient up\|auto` | `up` | `up` keeps every part as modelled, studs up. `auto` picks the face that needs the least support. See [Part orientation](#part-orientation). |
| `--orient-part PART=MODE` | none | Override one part. `MODE` is `up`, `flip` (upside down) or `auto`. Repeatable. |
| `--scale N` | `1.0` | Size multiplier. `1.0` is true LEGO size. Applies to every output. |

### Instructions

| Option | Default | Description |
|---|---|---|
| `--instructions` | off | Also download the official building instruction PDFs. |
| `--instructions-only` | off | Download only the instruction PDFs, nothing else. No Rebrickable key needed. |
| `--locale CODE` | `en-gb` | lego.com region used to look up instructions. |

### Library

| Option | Default | Description |
|---|---|---|
| `--ldraw PATH` | auto | Use an existing `ldraw` folder and skip the downloads. |

---

## Output files

Everything is written to the output folder (`--out`, or the set number / model name by default).

| File | When | Description |
|---|---|---|
| `<part>.stl` | always (unless `--no-part-stl`) | One STL per unique part, studs up, resting flat on the bed. |
| `manifest.csv` | always | One row per part: part number, LDraw id used, name, quantity, colours, status, Rebrickable URL and the ids that were tried. |
| `assembled.stl` | model-file mode | The whole model in its modelled positions. |
| `plate_NN.3mf` | `--3mf` | Every part instance packed onto bed-sized plates. |
| `plate_NN.stl` | `--plates` | The same plates as STL. |
| `plate_<colour>_NN.*` | `--by-colour` | Per-colour plates, e.g. `plate_red_01.3mf`. |
| `instructions/*.pdf` | `--instructions` | `42233_instructions_01_of_08.pdf` and so on. |

The LDraw library is cached in `./ldraw_cache/` in the folder you run the script from, so later runs are quick.

The console output lists every part with its status, including any parts it could not find geometry for. Those parts are marked `missing in LDraw` in the manifest, along with the ids that were tried.

---

## Examples

**Convert a set and lay it out for a 256 × 256 mm bed (3MF):**

```bash
python3 brickprint.py 42233 --3mf --bed 256 256
```

**Per-part STLs only, nothing else:**

```bash
python3 brickprint.py 75192-1
```

**Plates as both 3MF and STL, with more space between parts:**

```bash
python3 brickprint.py 42233 --3mf --plates --gap 5
```

**Print one colour at a time:**

```bash
python3 brickprint.py 42233 --3mf --by-colour
```

**Start from a model file and get the assembled model too:**

```bash
python3 brickprint.py 75033-1.mpd --3mf --by-colour --out 75033_plates
```

**Skip the per-part STLs and the assembled model, plates only:**

```bash
python3 brickprint.py 75033-1.mpd --3mf --no-part-stl --no-assembly
```

**Let the script choose orientations, but force two parts:**

```bash
python3 brickprint.py 42233 --3mf --orient auto --orient-part 3034=up --orient-part 3705=up
```

**Print a part upside down (studs down):**

```bash
python3 brickprint.py 42233 --3mf --orient-part 3034=flip
```

**Download just the instruction PDFs:**

```bash
python3 brickprint.py 42233 --instructions-only
```

**Everything at once, for a UK instructions page:**

```bash
python3 brickprint.py 42233 --3mf --instructions --locale en-gb
```

**Print at twice the size (for example, bigger models that mate with each other but not with real LEGO):**

```bash
python3 brickprint.py 42233 --3mf --scale 2
```

**Reuse an existing LDraw install and skip all downloads:**

```bash
python3 brickprint.py 75033-1.mpd --ldraw ~/ldraw --3mf
```

---

## Part orientation

On plates, parts are placed **studs up, as LDraw models them**, by default. LDraw models each part in its natural resting pose, so bricks and plates sit upright and long parts such as axles lie flat. Each part is also turned so its long side runs along the X axis.

Two other modes are available:

- **`--orient auto`** tries each of the six main faces as the bottom. It prefers the one with the least overhanging surface (faces pointing down more than 45 degrees), a larger flat contact area and a lower height. With no supports considered, this can put some parts, such as plates, on their side with studs sideways.
- **`--orient-part PART=MODE`** overrides a single part. Part numbers match the names in the console list and the manifest (for example `3034` or `32123b`).

The individual `<part>.stl` files are always written studs up.

---

## How it works

1. **Parts list.** In set mode, the Rebrickable API returns every part with its quantity, colours and LDraw ids. In model mode, the `.mpd` is parsed instead and submodels are flattened into individual part instances.
2. **Geometry.** Each part is resolved in the LDraw library by trying every known LDraw id, then the Rebrickable part number, then the base part for printed variants. A pack of unofficial LDraw parts is also downloaded as a fallback for newer parts. Official files win when both exist.
3. **Conversion.** LDraw `.dat` files are parsed (including sub-files, mirrored geometry and winding) into triangles. One LDraw unit is 0.4 mm, and LDraw's Y-down axes are rotated to Z-up for printing.
4. **Plates.** Parts are oriented, then packed row by row onto bed-sized plates, one 3MF object per part type, reused for every copy.

---

## Limitations

- **Not print-tuned.** The geometry is LDraw's visual geometry. Real LEGO clutch fit is extremely tight (around a hundredth of a millimetre), so true-size printed bricks usually won't clutch properly with each other or with real LEGO. Studs and tube holes typically need clearance adjustments tuned to your printer. This is not implemented yet.
- **Some parts have no geometry.** Stickers, cards, strings, rubber or flexible parts, and some very new or rare parts may be missing from LDraw. They are listed at the end of the run and in the manifest. Unofficial parts are used where available, but they have not been through LDraw's full review, so check them in your slicer.
- **Simple plate packing.** Layout is row by row, not optimised, so some bed space is wasted.
- **Orientation is a heuristic.** Only the six main faces are considered in `auto` mode, and no supports are generated. Check the slicer preview before long prints.
- **No colour in 3MF.** Plates are geometry only. Use `--by-colour` to split prints by colour.
- **Instruction downloads depend on lego.com's page layout.** The script reads the public building-instructions page for a set and downloads the PDFs it links to, one second apart. If lego.com changes the page, it may stop working. It is intended for personal use, so check LEGO's terms of use before doing anything more.
- **Assembling a new model from instruction PDFs is not supported.** The PDFs are 2D drawings and do not give reliable 3D part positions. If an LDraw model of the set exists, use model-file mode for the assembly.

---

## Troubleshooting

**`Set REBRICKABLE_KEY first`**
The environment variable is not set in the terminal you are using. See [Requirements](#requirements) for the commands for your shell. You can also pass an LDraw model file instead of a set number, which needs no key.

**`HTTP Error 401` or `403` from Rebrickable**
The API key is wrong, or has stray spaces or quotes around it.

**`HTTP Error 404`**
The set number was not found. Try the full form, such as `75192-1`.

**LDraw download fails**
Download `https://library.ldraw.org/library/updates/complete.zip` in your browser, save it as `ldraw_cache/complete.zip` in the folder you run the script from, and rerun. It will unzip it itself. The unofficial parts pack is optional, and the script continues without it if the download fails.

**A part says `missing in LDraw`**
The part has no geometry in either library. The manifest lists the ids that were tried and a Rebrickable link. Paper items such as activity cards will never have geometry.

**Parts look inside out or oddly oriented in the slicer**
Try `--orient-part PART=flip` for that part, or `--orient up`. If a specific part consistently looks wrong, please open an issue with the part number.

**`ImportError` or missing function errors**
Make sure you are running the latest `brickprint.py`, with no older copies alongside it.

---

## Credits and licensing

- Part data and inventories: [Rebrickable](https://rebrickable.com). Use of their API is subject to their terms.
- Part geometry: the [LDraw](https://www.ldraw.org) parts library, an open, community-maintained library. LDraw files are licensed under Creative Commons Attribution (CC BY 2.0 / 4.0). Keep the attribution if you redistribute any converted geometry.
- Model files: the [LDraw Official Model Repository](https://omr.ldraw.org) hosts models of many sets.

LEGO® is a trademark of the LEGO Group, which does not sponsor, authorise or endorse this project. This tool is intended for personal use, so check the terms of any data source before sharing or selling what you generate.

**Licence:** the code in this repository is released under the [MIT Licence](LICENSE). The LDraw parts library and Rebrickable data it downloads at run time are not part of this repository and remain under their own licences and terms, as described above.
