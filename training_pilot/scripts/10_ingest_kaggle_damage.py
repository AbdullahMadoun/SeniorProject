import hashlib
import shutil
from pathlib import Path
from tqdm import tqdm

from common import (
    ensure_clean_dir,
    read_yolo_rows,
    write_yolo_rows,
    resolve_project_root,
    IMAGE_SUFFIXES
)

def get_image_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def main():
    project_root = resolve_project_root()
    
    # Path to our current processed/deduplicated images
    current_data_dir = project_root / "data"
    
    # Path to newly downloaded Kaggle data
    extern_src = project_root / "data" / "raw" / "extern_download"
    
    # Target for fused diversity data
    extern_dst = project_root / "data" / "raw" / "extern_fused"
    ensure_clean_dir(extern_dst)
    (extern_dst / "images").mkdir(parents=True, exist_ok=True)
    (extern_dst / "labels").mkdir(parents=True, exist_ok=True)
    
    # 1. Build a hash map of our current verified images to prevent leakage
    print("Indexing existing dataset for deduplication...")
    existing_hashes = set()
    for ipath in current_data_dir.rglob("*"):
        if ipath.is_file() and ipath.suffix.lower() in IMAGE_SUFFIXES:
            existing_hashes.add(get_image_hash(ipath))
            
    print(f"Found {len(existing_hashes)} unique baseline images.")
    
    # 2. Ingest and Harmonize
    # Kaggle classes: 0:pothole, 1:alligator, 2:lateral, 3:longitudinal
    # Our project uses single-class damage: 0
    all_extern_images = sorted([p for p in extern_src.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES])
    
    added_count = 0
    skipped_dup = 0
    
    for ipath in tqdm(all_extern_images, desc="Ingesting External Data"):
        # Deduplication check
        ihash = get_image_hash(ipath)
        if ihash in existing_hashes:
            skipped_dup += 1
            continue
            
        lpath = ipath.with_suffix(".txt")
        if not lpath.exists():
            continue
            
        rows = read_yolo_rows(lpath)
        if not rows:
            continue
            
        # Harmonize: All classes -> 0
        harmonized_rows = [(0, bbox) for _, bbox in rows]
        
        # Save to fused folder
        safe_stem = f"extern_{ipath.stem}"
        dest_ipath = extern_dst / "images" / f"{safe_stem}{ipath.suffix.lower()}"
        dest_lpath = extern_dst / "labels" / f"{safe_stem}.txt"
        
        dest_ipath.parent.mkdir(parents=True, exist_ok=True)
        dest_lpath.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(ipath, dest_ipath)
        write_yolo_rows(dest_lpath, harmonized_rows)
        
        existing_hashes.add(ihash)
        added_count += 1
        
    print(f"Fusion Complete!")
    print(f"Added {added_count} new unique images.")
    print(f"Skipped {skipped_dup} duplicates.")

if __name__ == "__main__":
    main()
