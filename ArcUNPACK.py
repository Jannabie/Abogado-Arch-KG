#!/usr/bin/env python3
"""
ArcUNPACK.py - DSK Archive Unpacker + KG Image Decoder
Mengekstrak file .KG dari archive .DSK dan mengonversinya langsung ke .PNG
TANPA memerlukan GARbro atau tool eksternal lain.

Decoder dibangun dengan me-reverse-engineer ArcKGPACK.py (format packer).

Format KG:
  Header (0x30 bytes):
    0x00: "KG\\x00\\x{bpp_code}"  — magic + bpp_code (1=8bpp, 2=24bpp, 3=32bpp)
    0x04: width  (uint16 LE)
    0x06: height (uint16 LE)
    0x0C: palette_offset (uint32 LE) — 0x30 untuk 8bpp, 0 untuk 24bpp
    0x10: data_offset   (uint32 LE) — 0x430 untuk 8bpp, 0x30 untuk 24bpp

  Untuk 8bpp (indexed):
    [0x30..0x430] = 1024 bytes palette BGRA (256 warna × 4 byte)
    [0x430..]     = 1 channel RLE terkompresi (pixel indices)

  Untuk 24bpp (RGB):
    [0x30..] = 3 channel RLE berurutan: B, G, R
    Setiap channel byte-aligned (di-flush setelah selesai)

  Kompresi channel (RLE bit-level, MSB first):
    - 2 byte pertama = literal
    - Loop:
        flag1, flag2 = baca 1 bit, baca 1 bit
        "10" = RLE: repeat byte_terakhir sebanyak decode_count() kali
        "01" = literal: baca 8 bit, tulis sebagai byte

  Gambar disimpan FLIPPED (FLIP_TOP_BOTTOM), harus di-flip saat decode.

Usage:
  python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>

Contoh:
  python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/

Output per file:
  extracted/NAMA.png         — gambar hasil decode
  extracted/kg_metadata.json — metadata BPP, dipakai oleh ArcKGPACK.py
"""

import struct
import os
import sys
import json

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("[WARN] Pillow tidak ter-install. Hanya bisa ekstrak .KG mentah (tidak decode PNG).")
    print("       Install dengan: pip install Pillow")


# ──────────────────────────────────────────────────────────────────────────────
# PFT Reader (format sama dengan ArcPATCH.py)
# ──────────────────────────────────────────────────────────────────────────────

def read_pft(pft_path):
    """
    Baca file .PFT.
    Header: <HHi (header_size, cluster_size, count)
    Entry : <8sII (name[8], offset_idx, size)
    """
    with open(pft_path, "rb") as f:
        raw = f.read(8)
        if len(raw) < 8:
            raise ValueError(f"File PFT terlalu kecil: {pft_path}")
        header_size, cluster_size, count = struct.unpack("<HHi", raw)
        if cluster_size == 0:
            cluster_size = 2048
        f.seek(header_size)
        entries = []
        for _ in range(count):
            entry = f.read(16)
            if len(entry) < 16:
                break
            raw_name, offset_idx, size = struct.unpack("<8sII", entry)
            name = raw_name.split(b'\x00')[0].decode('ascii', errors='ignore').strip()
            if name:
                entries.append({'name': name, 'offset_idx': offset_idx, 'size': size})
    return cluster_size, entries


# ──────────────────────────────────────────────────────────────────────────────
# KG Bit Reader (inverse dari BitWriter di ArcKGPACK.py)
# BitWriter menulis MSB first → BitReader baca MSB first
# ──────────────────────────────────────────────────────────────────────────────

class KGBitReader:
    """
    Baca bit dari byte array, MSB first.
    Setiap channel terpisah secara byte-boundary (flush di akhir channel).
    Tracking posisi byte memungkinkan kita pindah ke channel berikutnya.
    """
    def __init__(self, data, byte_offset=0):
        self.data = data
        self.byte_pos = byte_offset
        self.bit_buf = 0
        self.bits_left = 0

    def read_bit(self):
        if self.bits_left == 0:
            if self.byte_pos >= len(self.data):
                return 0
            self.bit_buf = self.data[self.byte_pos]
            self.byte_pos += 1
            self.bits_left = 8
        bit = (self.bit_buf >> (self.bits_left - 1)) & 1
        self.bits_left -= 1
        return bit

    def read_bits(self, n):
        result = 0
        for _ in range(n):
            result = (result << 1) | self.read_bit()
        return result

    def align_to_byte(self):
        """Loncat ke byte boundary berikutnya (buang sisa bits di byte saat ini)."""
        self.bits_left = 0
        self.bit_buf = 0

    def current_byte_offset(self):
        return self.byte_pos

    def decode_run_count(self):
        """
        Inverse dari encode_count() di ArcKGPACK.py:
          count 1..3   → 2 bits (count)
          count 4..18  → "00" + 4 bits (count-3)
          count 19..255 → "00" + "0000" + 8 bits (count)
          count >= 256  → "00" + "0000" + "00000000" + 16 bits (count)
        """
        tag2 = self.read_bits(2)
        if tag2 != 0:
            return tag2          # 1, 2, atau 3
        tag4 = self.read_bits(4)
        if tag4 != 0:
            return tag4 + 3      # 4..18
        tag8 = self.read_bits(8)
        if tag8 != 0:
            return tag8          # 19..255
        return self.read_bits(16)  # 256..65535

    def decompress_channel(self, expected_len):
        """
        Inverse dari compress_channel() di ArcKGPACK.py.
        Baca bits sampai output = expected_len bytes,
        lalu align ke byte boundary untuk channel berikutnya.

        Algoritma packer:
          - Tulis byte[0] dan byte[1] sebagai literal (16 bits)
          - Loop dari i=2:
              current_val = byte terakhir yang diproses (data[i-1])
              Hitung run_length berapa byte berikutnya = current_val
              if run_length >= 2:
                  tulis "10" + encode_count(run_length)
                  skip run_length bytes
              else:
                  tulis "01" + byte[i] (8 bits)
                  skip 1 byte

        Jadi decoder:
          - Baca 2 literal byte pertama
          - Loop:
              baca 2 flag bit
              "10" → RLE: repeat byte_terakhir sebanyak decode_count() kali
              "01" → literal: baca 8 bits
        """
        output = bytearray()

        if expected_len == 0:
            self.align_to_byte()
            return bytes(output)

        # 2 byte pertama = literal
        output.append(self.read_bits(8))
        if expected_len > 1:
            output.append(self.read_bits(8))

        while len(output) < expected_len:
            remaining = expected_len - len(output)
            f1 = self.read_bit()
            f2 = self.read_bit()
            if f1 == 1 and f2 == 0:
                # RLE: repeat byte terakhir sebanyak count kali
                count = self.decode_run_count()
                last = output[-1] if output else 0
                take = min(count, remaining)
                output.extend([last] * take)
            else:
                # Literal byte (f1=0, f2=1)
                byte = self.read_bits(8)
                output.append(byte)

        # Setelah channel selesai, loncat ke byte boundary
        # (BitWriter.get_bytes() memanggil flush() yang pad dengan zeros)
        self.align_to_byte()
        return bytes(output[:expected_len])


# ──────────────────────────────────────────────────────────────────────────────
# KG Decoder (PNG output)
# ──────────────────────────────────────────────────────────────────────────────

BPP_NAMES = {1: '8bpp (indexed)', 2: '24bpp (RGB)', 3: '32bpp (RGBA)'}

def decode_kg(kg_data):
    """
    Decode data .KG ke PIL Image dan dict info BPP.
    Mengembalikan (PIL.Image, bpp_int) atau (None, None) jika gagal.
    """
    if len(kg_data) < 0x30:
        return None, None

    # Validasi magic
    if kg_data[0:2] != b'KG':
        return None, None

    bpp_code = kg_data[3]
    width  = struct.unpack_from("<H", kg_data, 0x04)[0]
    height = struct.unpack_from("<H", kg_data, 0x06)[0]
    pal_offset  = struct.unpack_from("<I", kg_data, 0x0C)[0]
    data_offset = struct.unpack_from("<I", kg_data, 0x10)[0]

    if width == 0 or height == 0:
        return None, None
    if data_offset == 0 or data_offset >= len(kg_data):
        # Coba fallback: 8bpp → data setelah header + palette, 24bpp → setelah header
        if bpp_code == 1:
            data_offset = 0x30 + 1024
        else:
            data_offset = 0x30

    pixel_count = width * height
    reader = KGBitReader(kg_data, data_offset)

    try:
        if bpp_code == 1:
            # ── 8bpp Indexed ──────────────────────────────────────────────────
            # Palette: 1024 bytes BGRA (256 × 4) di pal_offset
            if pal_offset == 0:
                pal_offset = 0x30
            pal_raw = kg_data[pal_offset: pal_offset + 1024]

            # Build Pillow palette (RGB, 768 bytes)
            pal_rgb = bytearray(768)
            for i in range(256):
                if i * 4 + 2 < len(pal_raw):
                    b = pal_raw[i * 4]
                    g = pal_raw[i * 4 + 1]
                    r = pal_raw[i * 4 + 2]
                else:
                    r, g, b = 0, 0, 0
                pal_rgb[i * 3]     = r
                pal_rgb[i * 3 + 1] = g
                pal_rgb[i * 3 + 2] = b

            # Decompress indices
            reader = KGBitReader(kg_data, data_offset)
            indices = reader.decompress_channel(pixel_count)

            img = Image.frombytes('P', (width, height), bytes(indices))
            img.putpalette(bytes(pal_rgb))
            img = img.convert('RGBA')

            bpp = 8

        elif bpp_code == 2:
            # ── 24bpp RGB ─────────────────────────────────────────────────────
            # 3 channel berurutan: B, G, R (masing-masing byte-aligned setelah selesai)
            b_ch = reader.decompress_channel(pixel_count)
            g_ch = reader.decompress_channel(pixel_count)
            r_ch = reader.decompress_channel(pixel_count)

            # Susun pixels RGB
            pixels = bytearray(pixel_count * 3)
            for i in range(pixel_count):
                pixels[i * 3]     = r_ch[i]
                pixels[i * 3 + 1] = g_ch[i]
                pixels[i * 3 + 2] = b_ch[i]

            img = Image.frombytes('RGB', (width, height), bytes(pixels))
            bpp = 24

        elif bpp_code == 3:
            # ── 32bpp RGBA ────────────────────────────────────────────────────
            # 4 channel: B, G, R, A
            b_ch = reader.decompress_channel(pixel_count)
            g_ch = reader.decompress_channel(pixel_count)
            r_ch = reader.decompress_channel(pixel_count)
            a_ch = reader.decompress_channel(pixel_count)

            pixels = bytearray(pixel_count * 4)
            for i in range(pixel_count):
                pixels[i * 4]     = r_ch[i]
                pixels[i * 4 + 1] = g_ch[i]
                pixels[i * 4 + 2] = b_ch[i]
                pixels[i * 4 + 3] = a_ch[i]

            img = Image.frombytes('RGBA', (width, height), bytes(pixels))
            bpp = 32

        else:
            return None, None

        # Gambar disimpan FLIPPED di KG (packer flip sebelum compress)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        return img, bpp

    except Exception as ex:
        print(f"   [WARN] Decode gagal: {ex}")
        return None, None


# ──────────────────────────────────────────────────────────────────────────────
# Main: Unpack DSK → extract KG → decode PNG
# ──────────────────────────────────────────────────────────────────────────────

def unpack_dsk(dsk_path, pft_path, output_dir):
    if not os.path.exists(dsk_path):
        print(f"[Error] File DSK tidak ditemukan: {dsk_path}")
        return False
    if not os.path.exists(pft_path):
        print(f"[Error] File PFT tidak ditemukan: {pft_path}")
        return False

    print(f"[*] Membaca index : {pft_path}")
    cluster_size, entries = read_pft(pft_path)
    print(f"[*] Cluster size  : {cluster_size} bytes")
    print(f"[*] Jumlah file   : {len(entries)}")

    print(f"[*] Membaca archive: {dsk_path}")
    with open(dsk_path, "rb") as f:
        archive_data = f.read()
    print(f"[*] Ukuran archive : {len(archive_data):,} bytes")

    os.makedirs(output_dir, exist_ok=True)

    metadata = {}   # untuk kg_metadata.json
    ok_png    = 0
    ok_kg     = 0
    failed    = 0

    for entry in entries:
        name       = entry['name']
        offset_idx = entry['offset_idx']
        size       = entry['size']

        if size == 0:
            print(f"[SKIP] {name}: size = 0")
            continue

        offset = offset_idx * cluster_size

        if offset + size > len(archive_data):
            print(f"[!]   {name}: offset out-of-bounds (blok={offset_idx}, size={size}), skip.")
            failed += 1
            continue

        kg_data = archive_data[offset: offset + size]

        # Simpan raw .KG (selalu)
        kg_out = os.path.join(output_dir, f"{name}.KG")
        with open(kg_out, "wb") as f:
            f.write(kg_data)

        # Decode ke PNG jika Pillow tersedia
        if HAS_PIL:
            img, bpp = decode_kg(kg_data)
            if img is not None:
                png_out = os.path.join(output_dir, f"{name}.png")
                img.save(png_out, 'PNG')
                w, h = img.size
                metadata[f"{name}.png"] = {"bpp": bpp, "width": w, "height": h}
                print(f"[+] {name}  →  {w}×{h}  {BPP_NAMES.get(bpp//8 if bpp==8 else bpp, str(bpp)+'bpp')}")
                ok_png += 1
            else:
                print(f"[+] {name}.KG  (decode gagal — disimpan raw)")
                ok_kg += 1
        else:
            print(f"[+] {name}.KG  (raw only — install Pillow untuk decode PNG)")
            ok_kg += 1

    # Simpan kg_metadata.json
    if metadata:
        meta_path = os.path.join(output_dir, "kg_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"\n[*] kg_metadata.json disimpan → {meta_path}")
        print(f"    (Digunakan otomatis oleh ArcKGPACK.py saat pack ulang)")

    print(f"\n[*] Selesai!")
    if HAS_PIL:
        print(f"    {ok_png} file ter-decode ke .PNG")
        if ok_kg:
            print(f"    {ok_kg} file disimpan raw .KG (decode gagal)")
    else:
        print(f"    {ok_png + ok_kg} file disimpan sebagai .KG mentah")
    if failed:
        print(f"    {failed} file GAGAL (offset out-of-bounds)")
    print(f"\n[*] Langkah selanjutnya:")
    print(f"    1. Edit file .PNG di image editor")
    print(f"    2. python ArcKGPACK.py {output_dir}/")
    print(f"    3. python ArcPATCH.py {os.path.basename(dsk_path)} {os.path.basename(pft_path)} packed_kg/")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("=" * 60)
        print("ArcUNPACK.py — DSK Unpacker + KG Image Decoder")
        print("=" * 60)
        print("\nCara penggunaan:")
        print("  python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>")
        print("\nContoh:")
        print("  python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/")
        print("\nOutput:")
        print("  extracted/NAMA.png          — gambar hasil decode (jika Pillow ter-install)")
        print("  extracted/NAMA.KG           — file .KG mentah (selalu disimpan)")
        print("  extracted/kg_metadata.json  — metadata BPP (untuk ArcKGPACK.py)")
        print("\nRequirements: pip install Pillow")
        print("=" * 60)
        sys.exit(1)

    ok = unpack_dsk(sys.argv[1], sys.argv[2], sys.argv[3])
    sys.exit(0 if ok else 1)
