import struct
import os
import sys

def read_pft(pft_path):
    """Read PFT index file."""
    with open(pft_path, "rb") as f:
        header_size, cluster_size, count = struct.unpack("<HHi", f.read(8))
        f.seek(header_size)
        
        entries = []
        for _ in range(count):
            raw_name, offset_idx, size = struct.unpack("<8sII", f.read(16))
            name = raw_name.split(b'\0')[0].decode('ascii', errors='ignore').strip()
            entries.append({
                'name': name,
                'offset_idx': offset_idx,
                'size': size
            })
        
        return header_size, cluster_size, entries

def unpack_dsk(dsk_path, pft_path, output_folder):
    """Unpack files from DSK archive using PFT index."""
    if not os.path.exists(dsk_path):
        print(f"[Error] DSK file not found: {dsk_path}")
        return False
    
    if not os.path.exists(pft_path):
        print(f"[Error] PFT file not found: {pft_path}")
        return False
        
    print(f"[Info] Reading PFT: {pft_path}")
    header_size, cluster_size, entries = read_pft(pft_path)
    
    print(f"[Info] Cluster size: {cluster_size}")
    print(f"[Info] Total files: {len(entries)}")
    
    os.makedirs(output_folder, exist_ok=True)
    
    unpacked_count = 0
    with open(dsk_path, "rb") as dsk:
        for entry in entries:
            name = entry['name']
            if not name:
                continue
                
            offset = entry['offset_idx'] * cluster_size
            size = entry['size']
            
            if size == 0:
                print(f"[Skip] {name} is empty (0 bytes).")
                continue
                
            dsk.seek(offset)
            data = dsk.read(size)
            
            out_file = os.path.join(output_folder, f"{name}.KG")
            with open(out_file, "wb") as f_out:
                f_out.write(data)
                
            print(f"[Unpacked] {name}.KG @ offset {offset} ({size} bytes)")
            unpacked_count += 1
            
    print(f"\n[Success] Unpacking complete!")
    print(f"  Unpacked: {unpacked_count} files to '{output_folder}'")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python ArcUNPACK.py <PFT_FILE> <DSK_FILE> <OUTPUT_FOLDER>")
    else:
        pft = sys.argv[1]
        dsk = sys.argv[2]
        out_dir = sys.argv[3]
        unpack_dsk(dsk, pft, out_dir)
