#!/usr/bin/env python3
"""
ArcUNPACK.py - DSK Archive Unpacker (Abogado KG)
Mengekstrak file-file .KG dari archive .DSK menggunakan index .PFT.

Setiap file di dalam .DSK aslinya berformat .KG (image proprietary Abogado Engine).
Script ini hanya mengekstrak data mentahnya — untuk mengonversi .KG ke .PNG
gunakan GARbro atau tool decoder terpisah, kemudian edit PNG-nya.

Setelah selesai edit, gunakan ArcKGPACK.py (PNG → .KG) lalu
ArcPATCH.py atau ArcPACK.py untuk memasukkan kembali ke arsip.

Usage:
  python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>

Contoh:
  python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/
"""

import struct
import os
import sys


def read_pft(pft_path):
    """
    Membaca file .PFT.
    Format header: <HHi (header_size, cluster_size, count)
    Format entry : <8sII (name[8], offset_idx, size)
    Mengembalikan (cluster_size, entries)
    """
    with open(pft_path, "rb") as f:
        header_raw = f.read(8)
        if len(header_raw) < 8:
            raise ValueError(f"File PFT terlalu kecil: {pft_path}")

        header_size, cluster_size, count = struct.unpack("<HHi", header_raw)

        if cluster_size == 0:
            cluster_size = 2048  # fallback default

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


def unpack_dsk(dsk_path, pft_path, output_dir):
    """
    Mengekstrak semua file .KG dari archive .DSK ke output_dir.
    File disimpan dengan nama sesuai PFT + ekstensi .KG
    """
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

    extracted = 0
    failed = 0

    for entry in entries:
        name       = entry['name']
        offset_idx = entry['offset_idx']
        size       = entry['size']

        if size == 0:
            print(f"[SKIP] {name}: size = 0, lewati.")
            continue

        # Offset = nomor blok × ukuran cluster
        offset = offset_idx * cluster_size

        if offset + size > len(archive_data):
            print(f"[!]   {name}: offset di luar batas (blok={offset_idx}, offset=0x{offset:08X}, size={size}), skip.")
            failed += 1
            continue

        # Ekstrak data mentah dan simpan sebagai .KG
        kg_data = archive_data[offset: offset + size]
        out_path = os.path.join(output_dir, f"{name}.KG")

        with open(out_path, "wb") as f:
            f.write(kg_data)

        print(f"[+] {name}.KG  (blok={offset_idx}, offset=0x{offset:08X}, size={size:,} bytes)")
        extracted += 1

    print(f"\n[*] Selesai — berhasil ekstrak {extracted}/{len(entries)} file ke: {output_dir}")
    if failed:
        print(f"[!] {failed} file gagal diekstrak (offset di luar batas).")
    print(f"\n[*] Langkah selanjutnya:")
    print(f"    1. Buka file .KG di GARbro (atau tool decoder) → export ke .PNG")
    print(f"    2. Edit file .PNG")
    print(f"    3. python ArcKGPACK.py <folder_png>/   → hasilkan .KG di packed_kg/")
    print(f"    4. python ArcPATCH.py {os.path.basename(dsk_path)} {os.path.basename(pft_path)} packed_kg/")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("=" * 60)
        print("ArcUNPACK.py — DSK Archive Unpacker (Abogado KG)")
        print("=" * 60)
        print("\nCara penggunaan:")
        print("  python ArcUNPACK.py <file.dsk> <file.pft> <output_folder>")
        print("\nContoh:")
        print("  python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/")
        print("\nOutput:")
        print("  Semua file .KG yang ada di dalam archive, disimpan di output_folder/")
        print("  Format file: NAME.KG (data mentah, belum di-decode ke PNG)")
        print("\nUntuk decode .KG → .PNG, gunakan GARbro atau tool lain.")
        print("=" * 60)
        sys.exit(1)

    dsk_file = sys.argv[1]
    pft_file = sys.argv[2]
    out_dir  = sys.argv[3]

    ok = unpack_dsk(dsk_file, pft_file, out_dir)
    sys.exit(0 if ok else 1)
