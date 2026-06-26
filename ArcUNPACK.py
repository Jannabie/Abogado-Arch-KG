#!/usr/bin/env python3
"""
ArcUNPACK.py - DSK Archive Unpacker for Abogado KG Graphics
Membongkar archive .DSK menggunakan index .PFT, mengekstrak file .KG,
lalu mengonversinya ke .PNG agar bisa diedit.

Workflow:
  1. Baca PFT index  
  2. Ekstrak setiap .KG dari .DSK berdasarkan offset*cluster_size
  3. Decode KG → PNG (8bpp / 24bpp / 32bpp)
  4. Simpan kg_metadata.json (BPP asli tiap gambar)

Usage:
  python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>

Contoh:
  python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/
"""

import struct
import os
import sys
import json

# ──────────────────────────────────────────────────────────────────────────────
# Optional Pillow import (only needed for KG→PNG decode)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ──────────────────────────────────────────────────────────────────────────────
# PFT Reader (sama persis dengan format di ArcPATCH.py)
# ──────────────────────────────────────────────────────────────────────────────

def read_pft(pft_path):
    """
    Membaca file .PFT dan mengembalikan (header_size, cluster_size, entries).
    entries = list of {'name':str, 'offset_idx':int, 'size':int}
    """
    with open(pft_path, "rb") as f:
        raw = f.read(8)
        if len(raw) < 8:
            raise ValueError("File PFT terlalu kecil, bukan PFT yang valid.")
        header_size, cluster_size, count = struct.unpack("<HHi", raw)

        f.seek(header_size)
        entries = []
        for _ in range(count):
            entry_raw = f.read(16)
            if len(entry_raw) < 16:
                break
            raw_name, offset_idx, size = struct.unpack("<8sII", entry_raw)
            name = raw_name.split(b'\x00')[0].decode('ascii', errors='ignore').strip()
            entries.append({'name': name, 'offset_idx': offset_idx, 'size': size})

    if cluster_size == 0:
        cluster_size = 2048  # default fallback

    return header_size, cluster_size, entries

# ──────────────────────────────────────────────────────────────────────────────
# BitReader for KG RLE decode
# ──────────────────────────────────────────────────────────────────────────────

class BitReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.byte = 0
        self.bits_left = 0

    def read_bits(self, count):
        result = 0
        while count > 0:
            if self.bits_left == 0:
                if self.pos >= len(self.data):
                    return result
                self.byte = self.data[self.pos]
                self.pos += 1
                self.bits_left = 8
            take = min(count, self.bits_left)
            shift = self.bits_left - take
            result = (result << take) | ((self.byte >> shift) & ((1 << take) - 1))
            self.bits_left -= take
            count -= take
        return result

# ──────────────────────────────────────────────────────────────────────────────
# KG RLE decompressor
# ──────────────────────────────────────────────────────────────────────────────

def decode_count(reader):
    """Decode run-length count (mirrors encode_count in ArcKGPACK.py)."""
    tag = reader.read_bits(2)
    if tag != 0:
        return tag  # 1..3
    tag2 = reader.read_bits(4)
    if tag2 != 0:
        return tag2 + 3  # 4..18
    tag3 = reader.read_bits(8)
    if tag3 != 0:
        return tag3  # 1..255
    return reader.read_bits(16)  # large count

def decompress_channel(data, expected_len):
    """Decompress one channel of KG RLE data."""
    reader = BitReader(data)
    output = bytearray()

    if expected_len == 0:
        return output

    # First two bytes are literals
    output.append(reader.read_bits(8))
    if expected_len > 1:
        output.append(reader.read_bits(8))

    while len(output) < expected_len:
        flag1 = reader.read_bits(1)
        flag2 = reader.read_bits(1)
        if flag1 == 1 and flag2 == 0:
            # RLE run: repeat last byte
            count = decode_count(reader)
            last = output[-1] if output else 0
            output.extend([last] * count)
        else:
            # Literal byte
            output.append(reader.read_bits(8))

    return bytes(output[:expected_len])

# ──────────────────────────────────────────────────────────────────────────────
# KG decoder
# ──────────────────────────────────────────────────────────────────────────────

def decode_kg_to_png(kg_data, output_path):
    """
    Decode file .KG ke file .PNG.
    Mengembalikan dict {'bpp': int, 'width': int, 'height': int} atau None jika gagal.
    """
    if not HAS_PIL:
        print("   [WARN] Pillow tidak ter-install. Hanya mengekstrak file .KG (skip decode PNG).")
        return None

    if len(kg_data) < 0x30:
        print(f"   [WARN] Data KG terlalu kecil ({len(kg_data)} bytes), skip decode.")
        return None

    magic = kg_data[0:2]
    if magic != b'KG':
        print(f"   [WARN] Magic bukan 'KG' ({magic!r}), skip decode.")
        return None

    bpp_code = kg_data[3]  # 1=8bpp indexed, 2=24bpp RGB, 3=32bpp RGBA
    width  = struct.unpack_from("<H", kg_data, 4)[0]
    height = struct.unpack_from("<H", kg_data, 6)[0]
    palette_offset = struct.unpack_from("<I", kg_data, 0x0C)[0]
    data_offset    = struct.unpack_from("<I", kg_data, 0x10)[0]

    if width == 0 or height == 0:
        print(f"   [WARN] Dimensi gambar tidak valid ({width}×{height}), skip decode.")
        return None

    bpp_map = {1: 8, 2: 24, 3: 32}
    bpp = bpp_map.get(bpp_code, 0)

    try:
        if bpp_code == 1:
            # 8bpp indexed: palette di offset 0x30 (1024 bytes BGRA), data setelah itu
            pal_raw = kg_data[palette_offset: palette_offset + 1024]
            comp_data = kg_data[data_offset:]
            indices = decompress_channel(comp_data, width * height)

            # Build PIL palette (RGB)
            pal_rgb = bytearray(768)
            for i in range(256):
                b = pal_raw[i*4]
                g = pal_raw[i*4 + 1]
                r = pal_raw[i*4 + 2]
                pal_rgb[i*3]   = r
                pal_rgb[i*3+1] = g
                pal_rgb[i*3+2] = b

            img = Image.frombytes('P', (width, height), bytes(indices))
            img.putpalette(bytes(pal_rgb))
            # Convert to RGBA to preserve transparency info
            img = img.convert('RGBA')

        elif bpp_code == 2:
            # 24bpp: tiga channel terkompresi (B, G, R) berurutan
            comp_data = kg_data[data_offset:]
            pixel_count = width * height
            reader = BitReader(comp_data)
            # Decompress each channel
            b_ch = decompress_channel(comp_data, pixel_count)
            # Estimate offset after B channel (rough, since we can't know exact size)
            # Use a two-pass approach: decompress sequentially from bytes
            b_ch, g_ch, r_ch = _decompress_rgb_channels(comp_data, pixel_count)
            pixels = bytearray(pixel_count * 3)
            for i in range(pixel_count):
                pixels[i*3]   = r_ch[i]
                pixels[i*3+1] = g_ch[i]
                pixels[i*3+2] = b_ch[i]
            img = Image.frombytes('RGB', (width, height), bytes(pixels))

        elif bpp_code == 3:
            # 32bpp RGBA: empat channel (B, G, R, A)
            comp_data = kg_data[data_offset:]
            pixel_count = width * height
            b_ch, g_ch, r_ch, a_ch = _decompress_rgba_channels(comp_data, pixel_count)
            pixels = bytearray(pixel_count * 4)
            for i in range(pixel_count):
                pixels[i*4]   = r_ch[i]
                pixels[i*4+1] = g_ch[i]
                pixels[i*4+2] = b_ch[i]
                pixels[i*4+3] = a_ch[i]
            img = Image.frombytes('RGBA', (width, height), bytes(pixels))

        else:
            print(f"   [WARN] BPP code tidak dikenal: {bpp_code}, skip decode.")
            return None

        # KG disimpan terbalik (flip vertical)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        img.save(output_path, 'PNG')
        return {'bpp': bpp, 'width': width, 'height': height}

    except Exception as ex:
        print(f"   [WARN] Gagal decode KG: {ex}")
        return None


def _decompress_rgb_channels(comp_data, pixel_count):
    """Decompress 3 sequential RLE channels (B, G, R) dari satu buffer."""
    reader = _SeqReader(comp_data)
    b_ch = _decompress_seq(reader, pixel_count)
    g_ch = _decompress_seq(reader, pixel_count)
    r_ch = _decompress_seq(reader, pixel_count)
    return b_ch, g_ch, r_ch


def _decompress_rgba_channels(comp_data, pixel_count):
    """Decompress 4 sequential RLE channels (B, G, R, A) dari satu buffer."""
    reader = _SeqReader(comp_data)
    b_ch = _decompress_seq(reader, pixel_count)
    g_ch = _decompress_seq(reader, pixel_count)
    r_ch = _decompress_seq(reader, pixel_count)
    a_ch = _decompress_seq(reader, pixel_count)
    return b_ch, g_ch, r_ch, a_ch


class _SeqReader:
    """Bit reader yang terus berlanjut posisi antar channel."""
    def __init__(self, data):
        self.data = data
        self.byte_pos = 0
        self.current_byte = 0
        self.bits_left = 0

    def read_bits(self, count):
        result = 0
        while count > 0:
            if self.bits_left == 0:
                if self.byte_pos >= len(self.data):
                    return result
                self.current_byte = self.data[self.byte_pos]
                self.byte_pos += 1
                self.bits_left = 8
            take = min(count, self.bits_left)
            shift = self.bits_left - take
            result = (result << take) | ((self.current_byte >> shift) & ((1 << take) - 1))
            self.bits_left -= take
            count -= take
        return result


def _decode_count_seq(reader):
    tag = reader.read_bits(2)
    if tag != 0:
        return tag
    tag2 = reader.read_bits(4)
    if tag2 != 0:
        return tag2 + 3
    tag3 = reader.read_bits(8)
    if tag3 != 0:
        return tag3
    return reader.read_bits(16)


def _decompress_seq(reader, expected_len):
    output = bytearray()
    if expected_len == 0:
        return output
    output.append(reader.read_bits(8))
    if expected_len > 1:
        output.append(reader.read_bits(8))
    while len(output) < expected_len:
        f1 = reader.read_bits(1)
        f2 = reader.read_bits(1)
        if f1 == 1 and f2 == 0:
            count = _decode_count_seq(reader)
            last = output[-1] if output else 0
            output.extend([last] * count)
        else:
            output.append(reader.read_bits(8))
    return bytes(output[:expected_len])

# ──────────────────────────────────────────────────────────────────────────────
# Main unpack logic
# ──────────────────────────────────────────────────────────────────────────────

def unpack_dsk(dsk_path, pft_path, output_dir):
    if not os.path.exists(dsk_path):
        print(f"[Error] File DSK tidak ditemukan: {dsk_path}")
        return False
    if not os.path.exists(pft_path):
        print(f"[Error] File PFT tidak ditemukan: {pft_path}")
        return False

    print(f"[*] Membaca index: {pft_path}")
    header_size, cluster_size, entries = read_pft(pft_path)
    print(f"[*] Header size : {header_size} bytes")
    print(f"[*] Cluster size: {cluster_size} bytes")
    print(f"[*] Jumlah file : {len(entries)}")

    print(f"[*] Membaca archive: {dsk_path}")
    with open(dsk_path, "rb") as f:
        archive_data = f.read()
    print(f"[*] Ukuran archive: {len(archive_data):,} bytes")

    os.makedirs(output_dir, exist_ok=True)

    metadata = {}
    extracted = 0
    failed = 0

    for entry in entries:
        name      = entry['name']
        offset_idx= entry['offset_idx']
        size      = entry['size']

        if size == 0:
            print(f"[SKIP] {name}: ukuran 0, lewati.")
            continue

        offset = offset_idx * cluster_size

        if offset + size > len(archive_data):
            print(f"[!] {name}: offset di luar batas (offset_idx={offset_idx}, size={size}), skip.")
            failed += 1
            continue

        kg_data = archive_data[offset: offset + size]
        kg_out  = os.path.join(output_dir, f"{name}.KG")
        png_out = os.path.join(output_dir, f"{name}.png")

        # Selalu simpan file .KG mentah terlebih dulu
        with open(kg_out, "wb") as f:
            f.write(kg_data)

        # Decode ke PNG
        info = decode_kg_to_png(kg_data, png_out)
        if info:
            filename = f"{name}.png"
            metadata[filename] = {
                "bpp"   : info['bpp'],
                "width" : info['width'],
                "height": info['height']
            }
            print(f"[+] {name}: {info['width']}×{info['height']} {info['bpp']}bpp → {name}.png")
        else:
            # Tidak bisa decode, simpan mentah .KG saja
            print(f"[+] {name}: disimpan sebagai .KG (decode gagal/skip)")
        extracted += 1

    # Simpan kg_metadata.json
    if metadata:
        meta_path = os.path.join(output_dir, "kg_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"\n[*] Metadata disimpan: {meta_path}")

    print(f"\n[*] Selesai! Berhasil ekstrak {extracted}/{len(entries)} file ke: {output_dir}")
    if failed:
        print(f"[!] {failed} file gagal (offset di luar batas).")
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("=" * 60)
        print("ArcUNPACK.py - DSK Archive Unpacker (Abogado KG)")
        print("=" * 60)
        print("\nCara penggunaan:")
        print("  python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>")
        print("\nContoh:")
        print("  python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/")
        print("\nOutput:")
        print("  - File .KG mentah dari archive")
        print("  - File .PNG (hasil decode KG)")
        print("  - kg_metadata.json (BPP asli, digunakan saat ArcKGPACK.py)")
        print("=" * 60)
        sys.exit(1)

    dsk_file = sys.argv[1]
    pft_file = sys.argv[2]
    out_dir  = sys.argv[3]

    ok = unpack_dsk(dsk_file, pft_file, out_dir)
    sys.exit(0 if ok else 1)
