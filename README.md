# Abogado Arch KG

An image toolkit for the archive files of the visual novel **Shuumatsu no Sugoshikata ～The World is Drawing to an W/end.～**, built on the Abogado Engine.

---

## What Is This?

This game stores all of its image assets in a proprietary binary format called `.KG`, which is packed into one large archive file with a `.DSK` extension. The archive is indexed by a companion file with a `.PFT` extension, which stores the list of filenames, offset positions, and slot sizes of each image inside the archive.

This toolkit bridges all of that — from unpacking the archive, converting images into an editable format, recompressing edited images back into `.KG` format, to injecting modified files directly into the archive without needing to unpack everything again.

The `.KG` format itself supports three color depths: **8bpp** (indexed/palette), **24bpp** (RGB), and **32bpp** (RGBA). Each has a different header structure and compression algorithm, and this toolkit handles all three automatically.

---

## File Structure

| File | Role |
|---|---|
| `ArcUNPACK.py` | Extracts all `.KG` files from the `.DSK` archive using the `.PFT` index |
| `ArcKGPACK.py` | Converts `.png` files back into `.KG` format with the appropriate compression |
| `ArcPACK.py` | Generic packer for rebuilding the `.DSK` archive from scratch |
| `ArcPATCH.py` | Injects modified `.KG` files directly into the `.DSK` archive |

---

## About `kg_metadata.json`

When images are extracted from the archive, information about their original color depth (8bpp, 24bpp, or 32bpp) is stored in a `kg_metadata.json` file inside the extraction output folder. This file is important — during the repacking process, `ArcKGPACK.py` reads this metadata to ensure each image is repacked in the exact same BPP format as the original. If an image that was originally 8bpp gets packed as 24bpp, the game may fail to load it or the display may be corrupted.

---

## How to Use

Full workflow (full roundtrip):

### Step 0 — Unpack DSK → PNG (directly, no other tool needed)

```bash
python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/
```

Output in the `extracted/` folder:
- All `.KG` files (raw)
- All `.PNG` files automatically decoded (8bpp/24bpp/32bpp)
- `kg_metadata.json` containing the original BPP of each image (read by ArcKGPACK.py)

### Step 1 — Edit the images

Open and edit the `.PNG` files in any image editor.

> **Important:** Do not delete `kg_metadata.json` from the folder. This file
> determines the BPP format used during repacking later.

### Step 2 — Convert PNG Back to .KG Format

Once you've finished editing the PNGs:

```bash
python ArcKGPACK.py extracted/
```

The converted output is automatically saved in the `extracted/packed_kg/` subfolder.

### Step 3 — Patch into the DSK Archive

```bash
python ArcPATCH.py GRAPHIC.dsk GRAPHIC.pft extracted/packed_kg/
```

`ArcPATCH.py` works **in-place** — only the files present in the patch folder are replaced.
The size of the packed output **must not exceed the original slot size** in the PFT;
if it's larger, the file is skipped and marked `[Skip]`.

### About ArcPACK

`ArcPACK.py` is used to rebuild the `.DSK` archive from scratch — for example, if you want to
add new files. It's needed less often than `ArcPATCH.py`.

---

## Requirements

This tool requires **Python 3.x** and the **Pillow** library for image processing. Dependencies can be installed with:

```bash
pip install Pillow
```

---

## Game Archive File Structure

| File | Description |
|---|---|
| `GRAPHIC.DSK` (or other name) | Main archive containing all `.KG` files |
| `GRAPHIC.PFT` | Index file paired with `.DSK`, containing the name, offset, and size of each file |
| `kg_metadata.json` | BPP metadata from extraction, read during the repacking process |

---

## Before You Start

Always **back up the original `.DSK` and `.PFT` files** before running the patch process. The patch operation writes directly to the archive file permanently, and there is no automatic undo mechanism.

---

## Disclaimer

This toolkit is created solely for educational, research, and personal modification purposes. Users are fully responsible for ensuring their use complies with the copyright rules and Terms of Service of the original game.

---

## Contributing

Pull requests and issues are very welcome. For major changes, please open an issue first so it can be discussed before implementation.
