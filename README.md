# Abogado Arch KG

Image toolkit untuk file arsip visual novel **Shuumatsu no Sugoshikata ～The World is Drawing to an W/end.～** berbasis Abogado Engine.

---

## Apa Ini?

Game ini menyimpan semua aset gambarnya dalam format biner proprietary bernama `.KG`, yang dikemas ke dalam satu file arsip besar berekstensi `.DSK`. Arsip tersebut diindeks oleh file pasangannya berekstensi `.PFT`, yang menyimpan daftar nama file, posisi offset, dan ukuran slot masing-masing gambar di dalam arsip.

Toolkit ini hadir untuk menjembatani semua itu — dari membongkar arsip, mengonversi gambar ke format yang bisa diedit, mengompresi ulang hasil editan kembali ke format `.KG`, hingga menyuntikkan file yang sudah dimodifikasi langsung ke dalam arsip tanpa perlu membongkar ulang semuanya.

Format `.KG` sendiri mendukung tiga kedalaman warna: **8bpp** (indexed/palette), **24bpp** (RGB), dan **32bpp** (RGBA). Masing-masing punya struktur header dan algoritma kompresi yang berbeda, dan toolkit ini menangani ketiganya secara otomatis.

---

## Struktur File

| File | Peran |
|---|---|
| `ArcUNPACK.py` | Mengekstrak semua file `.KG` dari archive `.DSK` menggunakan index `.PFT` |
| `ArcKGPACK.py` | Mengonversi file `.png` kembali ke format `.KG` dengan kompresi yang sesuai |
| `ArcPACK.py` | Generic packer untuk membangun ulang arsip `.DSK` dari nol |
| `ArcPATCH.py` | Menyuntikkan file `.KG` yang sudah dimodifikasi ke dalam arsip `.DSK` secara langsung |

---

## Tentang `kg_metadata.json`

Ketika gambar diekstrak dari arsip, informasi tentang kedalaman warna aslinya (8bpp, 24bpp, atau 32bpp) disimpan dalam sebuah file `kg_metadata.json` di folder hasil ekstrak. File ini penting — saat proses packing ulang, `ArcKGPACK.py` membaca metadata ini untuk memastikan setiap gambar dikemas kembali dalam format BPP yang sama persis dengan aslinya. Jika gambar yang aslinya 8bpp dikemas sebagai 24bpp, game bisa gagal memuatnya atau tampilannya akan rusak.

---

## Cara Pakai

Alur kerja lengkap (full roundtrip):

### Tahap 0 — Ekstrak File .KG dari Archive DSK

```bash
python ArcUNPACK.py GRAPHIC.dsk GRAPHIC.pft extracted/
```

Output: semua file `.KG` tersimpan di folder `extracted/` dengan nama sesuai index PFT.
File `.KG` adalah format gambar biner proprietary Abogado Engine — belum bisa langsung diedit.

### Tahap 1 — Decode .KG ke PNG (pakai GARbro)

Buka file `.KG` hasil ekstrak menggunakan **GARbro** (atau tool image decoder lain),
lalu export ke format `.PNG`. Setelah itu edit PNG sesuai kebutuhan.

> **Penting:** `kg_metadata.json` tidak dibuat otomatis. Catat BPP asli setiap file
> (8bpp / 24bpp / 32bpp) yang tampil di GARbro, karena dibutuhkan saat pack ulang.

### Tahap 2 — Konversi PNG kembali ke Format .KG

Setelah selesai mengedit PNG:

```bash
# Memproses satu file
python ArcKGPACK.py gambar.png

# Memproses seluruh folder sekaligus
python ArcKGPACK.py folder_png/
```

Hasil konversi tersimpan otomatis di subfolder `packed_kg/` dalam folder yang sama.
Jika `kg_metadata.json` ditemukan di folder tersebut, BPP target tiap gambar akan dibaca darinya.
Jika tidak ada, packer mencoba mendeteksi format secara otomatis.

### Tahap 3 — Patch ke Arsip DSK

Setelah file `.KG` siap di `packed_kg/`, suntikkan ke arsip `.DSK`:

```bash
python ArcPATCH.py GRAPHIC.dsk GRAPHIC.pft packed_kg/
```

`ArcPATCH.py` bekerja **in-place** — hanya file yang ada di dalam folder patch yang diganti.
File lain dibiarkan apa adanya. Ukuran file hasil pack **tidak boleh melebihi slot asli** di PFT;
jika lebih besar, file tersebut dilewati dan ditandai `[Skip]`.

### Tentang ArcPACK

`ArcPACK.py` digunakan untuk membangun ulang arsip `.DSK` dari nol — misalnya jika ingin
menambahkan file baru. Lebih jarang dibutuhkan dibanding `ArcPATCH.py`.

---

## Requirements

Tool ini membutuhkan **Python 3.x** dan library **Pillow** untuk pemrosesan gambar. Instalasi dependensi bisa dilakukan dengan:

```bash
pip install Pillow
```

---

## Struktur File Arsip Game

| File | Keterangan |
|---|---|
| `GRAPHIC.DSK` (atau nama lain) | Arsip utama yang berisi semua file `.KG` |
| `GRAPHIC.PFT` | File indeks pasangan `.DSK`, berisi nama, offset, dan ukuran tiap file |
| `kg_metadata.json` | Metadata BPP hasil ekstrak, dibaca saat proses packing ulang |

---

## Sebelum Mulai

Selalu **backup file `.DSK` dan `.PFT` original** sebelum menjalankan proses patch. Operasi patch menulis langsung ke file arsip secara permanen, dan tidak ada mekanisme undo otomatis.

---

## Disclaimer

Toolkit ini dibuat semata-mata untuk keperluan edukasi, penelitian, dan modifikasi personal. Pengguna bertanggung jawab penuh untuk memastikan penggunaannya sesuai dengan aturan copyright dan Terms of Service dari game original.

---

## Kontribusi

Pull request dan issue sangat welcome. Untuk perubahan besar, sebaiknya buka issue terlebih dahulu agar bisa didiskusikan sebelum implementasi.
