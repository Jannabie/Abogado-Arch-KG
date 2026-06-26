#!/usr/bin/env python3
"""
ArcUNPACK.py - DSK Archive Unpacker + KG Image Decoder
Mengekstrak file .KG dari archive .DSK dan mengonversinya langsung ke .PNG
TANPA memerlukan GARbro atau tool eksternal lain.

Format ini mendukung dua versi KG:
- Versi 0 (digunakan oleh ArcKGPACK.py) - kompresi RLE sederhana
- Versi 2 (digunakan asli oleh game) - spatial LZ compression dengan dictionary

Usage:
  1. Unpack DSK & decode ke folder:
     python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>
  
  2. Decode langsung folder berisi file .KG/.SCF mentah:
     python ArcUNPACK.py <folder>
"""

import struct
import os
import sys
import json
import glob

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("[WARN] Pillow tidak ter-install. Hanya bisa ekstrak .KG mentah (tidak decode PNG).")
    print("       Install dengan: pip install Pillow")

# ──────────────────────────────────────────────────────────────────────────────
# PFT Reader
# ──────────────────────────────────────────────────────────────────────────────

def read_pft(pft_path):
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
# KG Decoder (Full Spatial LZ + Dictionary)
# ──────────────────────────────────────────────────────────────────────────────

class KgReader:
    def __init__(self, data, data_offset, width, height, bpp, pal_offset, alpha_offset):
        self.data = data
        self.pos = data_offset
        self.width = width
        self.height = height
        self.bpp = bpp
        self.pixel_size = bpp // 8
        self.stride = self.pixel_size * width
        self.output = bytearray(self.stride * height)
        self.pal_offset = pal_offset
        self.alpha_offset = alpha_offset
        
        self.buf = 0
        self.left = 0
        self.dict = bytearray(0x800)
    
    def reset_dict(self):
        for i in range(0x800):
            self.dict[i] = i & 7

    def get_bit(self):
        if self.left == 0:
            if self.pos >= len(self.data): return -1
            self.buf = self.data[self.pos]; self.pos += 1; self.left = 8
        b = (self.buf >> (self.left-1)) & 1; self.left -= 1; return b

    def get_bits(self, n):
        r = 0
        for _ in range(n):
            bit = self.get_bit()
            if bit == -1: return -1
            r = (r << 1) | bit
        return r
        
    def reset_bits(self):
        self.left = 0
        self.buf = 0

    def get_count(self):
        count = self.get_bits(2)
        if count == 0:
            count = self.get_bits(4)
            if count != 0:
                count += 3
            else:
                count = self.get_bits(8)
                if count == 0:
                    count = self.get_bits(16)
                    if count == 0:
                        count = (self.get_bits(16) << 16) | self.get_bits(16)
        return count

    def get_pixel(self, dst):
        if self.get_bits(1) == 1:
            return self.get_bits(8)
        else:
            n = 8 * self.output[dst - self.pixel_size]
            return self.dict[n + self.get_bits(3)]

    def update_dict(self, b, prev):
        s = 8 * prev
        for i in range(8):
            if self.dict[s + i] == b:
                break
        else:
            i = 8
            
        if i != 0:
            if i == 8: i = 7
            self.dict[s+1 : s+1+i] = self.dict[s : s+i]
            self.dict[s] = b

    def unpack_channel(self, dst):
        self.output[dst] = self.get_bits(8)
        dst += self.pixel_size
        self.output[dst] = self.get_bits(8)
        dst += self.pixel_size
        
        while dst < len(self.output):
            ctl = self.get_bits(1)
            if ctl == -1: break
            
            if ctl == 0:
                b = self.get_pixel(dst)
                self.output[dst] = b
                self.update_dict(b, self.output[dst - self.pixel_size])
                dst += self.pixel_size
                continue
                
            if self.get_bits(1) != 0:
                ctl = self.get_bits(2)
            else:
                ctl = 4
                
            if ctl == 0: offset = self.stride
            elif ctl == 1: offset = self.stride - self.pixel_size
            elif ctl == 2: offset = self.stride + self.pixel_size
            elif ctl == 3: offset = 2 * self.pixel_size
            else: offset = self.pixel_size
            
            count = self.get_count()
            src = dst - offset
            for _ in range(count):
                self.output[dst] = self.output[src]
                dst += self.pixel_size
                src += self.pixel_size
                
    def convert_to_bgr32(self):
        self.stride = self.width * 4
        pixels = bytearray(self.stride * self.height)
        dst = 0
        if self.pixel_size == 1:
            pass 
        else:
            for src in range(0, len(self.output), self.pixel_size):
                pixels[dst] = self.output[src]
                pixels[dst+1] = self.output[src+1]
                pixels[dst+2] = self.output[src+2]
                dst += 4
        self.output = pixels
        self.pixel_size = 4

    def unpack(self):
        self.reset_dict()
        self.unpack_channel(0)
        if self.pixel_size > 1:
            self.unpack_channel(1)
            self.unpack_channel(2)
            
        if self.alpha_offset != 0:
            self.convert_to_bgr32()
            self.pos = self.alpha_offset
            self.reset_bits()
            self.reset_dict()
            self.unpack_channel(3)


BPP_NAMES = {1: "8bpp (indexed)", 2: "24bpp (RGB)", 3: "32bpp (RGBA)"}

def decode_kg(kg_data):
    if len(kg_data) < 0x30:
        return None, None
    if kg_data[0:2] != b"KG":
        return None, None

    version = kg_data[2]
    bpp_code = kg_data[3]
    width  = struct.unpack_from("<H", kg_data, 0x04)[0]
    height = struct.unpack_from("<H", kg_data, 0x06)[0]
    pal_offset  = struct.unpack_from("<I", kg_data, 0x0C)[0]
    data_offset = struct.unpack_from("<I", kg_data, 0x10)[0]
    
    alpha_offset = 0
    if version == 2:
        alpha_offset = struct.unpack_from("<I", kg_data, 0x2C)[0]

    if width == 0 or height == 0: return None, None
    if data_offset == 0 or data_offset >= len(kg_data):
        if bpp_code == 1: data_offset = 0x30 + 1024
        else: data_offset = 0x30

    bpp = 24 if bpp_code == 2 else 8

    try:
        reader = KgReader(kg_data, data_offset, width, height, bpp, pal_offset, alpha_offset)
        reader.unpack()

        if bpp == 8:
            if pal_offset == 0: pal_offset = 0x30
            pal_data = kg_data[pal_offset : pal_offset + 1024]
            pal_rgb = bytearray(768)
            for i in range(256):
                if i*4+2 < len(pal_data):
                    pal_rgb[i*3]   = pal_data[i*4+2]
                    pal_rgb[i*3+1] = pal_data[i*4+1]
                    pal_rgb[i*3+2] = pal_data[i*4]
            img = Image.frombytes("P", (width, height), bytes(reader.output))
            img.putpalette(bytes(pal_rgb))
            img = img.convert("RGBA")
            bpp_out = 8
        else:
            px = width * height
            if reader.alpha_offset != 0:
                rgba = bytearray(px * 4)
                for i in range(px):
                    rgba[i*4]   = reader.output[i*4+2]
                    rgba[i*4+1] = reader.output[i*4+1]
                    rgba[i*4+2] = reader.output[i*4]
                    rgba[i*4+3] = reader.output[i*4+3]
                img = Image.frombytes("RGBA", (width, height), bytes(rgba))
                bpp_out = 32
            else:
                rgb = bytearray(px * 3)
                for i in range(px):
                    rgb[i*3]   = reader.output[i*3+2]
                    rgb[i*3+1] = reader.output[i*3+1]
                    rgb[i*3+2] = reader.output[i*3]
                img = Image.frombytes("RGB", (width, height), bytes(rgb))
                bpp_out = 24

        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        return img, bpp_out

    except Exception as ex:
        print(f"   [WARN] Decode gagal: {ex}")
        return None, None


# ──────────────────────────────────────────────────────────────────────────────
# Main Functions
# ──────────────────────────────────────────────────────────────────────────────

def process_file(file_path, output_dir, metadata):
    try:
        with open(file_path, "rb") as f:
            kg_data = f.read()
    except Exception as e:
        print(f"[!] Gagal membaca {file_path}: {e}")
        return False
        
    if kg_data[0:2] != b"KG":
        return False
        
    name = os.path.basename(file_path)
    if name.upper().endswith(".SCF"):
        name = name[:-4] + ".KG"
        
    if HAS_PIL:
        img, bpp = decode_kg(kg_data)
        if img is not None:
            png_name = os.path.splitext(name)[0] + ".png"
            png_out = os.path.join(output_dir, png_name)
            img.save(png_out, "PNG")
            w, h = img.size
            metadata[png_name] = {"bpp": bpp, "width": w, "height": h}
            print(f"[+] {name}  →  {w}x{h}  {BPP_NAMES.get(bpp//8 if bpp==8 else bpp, str(bpp)+'bpp')}")
            return True
        else:
            print(f"[-] {name}  (decode gagal)")
            return False
    else:
        return False

def decode_folder(folder_path):
    print(f"[*] Mencari file .KG / .SCF di {folder_path} ...")
    files = []
    for ext in ("*.KG", "*.kg", "*.SCF", "*.scf"):
        files.extend(glob.glob(os.path.join(folder_path, ext)))
        
    if not files:
        print("[-] Tidak ada file KG/SCF yang ditemukan.")
        return False
        
    metadata = {}
    ok_png = 0
    for file_path in files:
        if process_file(file_path, folder_path, metadata):
            ok_png += 1
            
    if metadata:
        meta_path = os.path.join(folder_path, "kg_metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                try:
                    old_metadata = json.load(f)
                    old_metadata.update(metadata)
                    metadata = old_metadata
                except: pass
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"[*] kg_metadata.json disimpan → {meta_path}")
        
    print(f"[*] Selesai! {ok_png} file ter-decode ke .PNG")
    return True


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

    os.makedirs(output_dir, exist_ok=True)

    metadata = {}
    ok_png    = 0
    ok_kg     = 0
    failed    = 0

    for entry in entries:
        name       = entry["name"]
        offset_idx = entry["offset_idx"]
        size       = entry["size"]

        if size == 0: continue
        offset = offset_idx * cluster_size

        if offset + size > len(archive_data):
            print(f"[!]   {name}: offset out-of-bounds, skip.")
            failed += 1
            continue

        kg_data = archive_data[offset: offset + size]
        kg_out = os.path.join(output_dir, f"{name}.KG")
        with open(kg_out, "wb") as f:
            f.write(kg_data)

        if HAS_PIL:
            img, bpp = decode_kg(kg_data)
            if img is not None:
                png_out = os.path.join(output_dir, f"{name}.png")
                img.save(png_out, "PNG")
                w, h = img.size
                metadata[f"{name}.png"] = {"bpp": bpp, "width": w, "height": h}
                print(f"[+] {name}  →  {w}x{h}  {BPP_NAMES.get(bpp//8 if bpp==8 else bpp, str(bpp)+'bpp')}")
                ok_png += 1
            else:
                print(f"[+] {name}.KG  (decode gagal — disimpan raw)")
                ok_kg += 1
        else:
            print(f"[+] {name}.KG  (raw only)")
            ok_kg += 1

    if metadata:
        meta_path = os.path.join(output_dir, "kg_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"\n[*] kg_metadata.json disimpan")

    print(f"\n[*] Selesai!")
    return True


if __name__ == "__main__":
    if len(sys.argv) == 2:
        # Mode decode folder
        decode_folder(sys.argv[1])
    elif len(sys.argv) == 4:
        # Mode unpack DSK
        unpack_dsk(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("=" * 60)
        print("ArcUNPACK.py — DSK Unpacker & KG Decoder (Full Format)")
        print("=" * 60)
        print("\nUsage Mode 1 (Unpack DSK & Decode):")
        print("  python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>")
        print("\nUsage Mode 2 (Decode direktori .KG / .SCF):")
        print("  python ArcUNPACK.py <folder_berisi_KG_atau_SCF>")
        print("=" * 60)
        sys.exit(1)
