from __future__ import annotations

import argparse
from pathlib import Path
from PIL import Image
from tqdm import tqdm

from common import (
    ensure_clean_dir,
    load_boxes_norm,
    read_yolo_rows,
    resolve_project_root,
    write_yolo_rows,
    IMAGE_SUFFIXES
)

def tile_positions(length: int, tile_size: int, overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    stride = tile_size - overlap
    positions = list(range(0, max(length - tile_size, 0) + 1, stride))
    last = length - tile_size
    if positions[-1] != last:
        positions.append(last)
    return positions

def map_box_to_tile(
    box_norm: list[float], 
    img_w: int, img_h: int, 
    tx: int, ty: int, tw: int, th: int
) -> list[float] | None:
    # box_norm is [cx, cy, w, h] in normalized 0-1 image space
    cx, cy, bw, bh = box_norm
    # Absolute pixels
    acx, acy, abw, abh = cx * img_w, cy * img_h, bw * img_w, bh * img_h
    
    # Box edges in pixels
    x1, y1 = acx - abw/2, acy - abh/2
    x2, y2 = acx + abw/2, acy + abh/2
    
    # Intersection with tile
    ix1, iy1 = max(x1, tx), max(y1, ty)
    ix2, iy2 = min(x2, tx+tw), min(y2, ty+th)
    
    iw, ih = ix2 - ix1, iy2 - iy1
    if iw <= 0 or ih <= 0:
        return None
        
    # Check if a significant portion of the box is in the tile (e.g. 30%)
    # This prevents tiny slivers of boxes from being counted as 'objects'
    if iw * ih < 0.3 * abw * abh:
        return None
        
    # Relative center and size in tile pixels
    tcx = (ix1 + ix2) / 2 - tx
    tcy = (iy1 + iy2) / 2 - ty
    
    # Normalize by tile size
    return [tcx / tw, tcy / th, iw / tw, ih / th]

def process_split(split: str, src_root: Path, dst_root: Path, tile_size: int, overlap: int):
    img_src = src_root / split / "images"
    lbl_src = src_root / split / "labels"
    
    img_dst = dst_root / split / "images"
    lbl_dst = dst_root / split / "labels"
    
    ensure_clean_dir(img_dst)
    ensure_clean_dir(lbl_dst)
    
    image_paths = sorted([p for p in img_src.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES])
    
    for ipath in tqdm(image_paths, desc=f"Tiling {split}"):
        lpath = lbl_src / f"{ipath.stem}.txt"
        if not lpath.exists():
            continue
            
        rows = read_yolo_rows(lpath)
        with Image.open(ipath) as img:
            w, h = img.size
            xs = tile_positions(w, tile_size, overlap)
            ys = tile_positions(h, tile_size, overlap)
            
            for tx in xs:
                for ty in ys:
                    tw = min(tile_size, w - tx)
                    th = min(tile_size, h - ty)
                    
                    tile_rows = []
                    for cls_id, box_norm in rows:
                        tbox = map_box_to_tile(box_norm, w, h, tx, ty, tw, th)
                        if tbox:
                            tile_rows.append((cls_id, tbox))
                    
                    # Only save tiles that contain objects to "Double the Recall" signal-to-noise
                    if not tile_rows:
                        continue
                        
                    tile_id = f"{ipath.stem}__x{tx}_y{ty}"
                    tile_img = img.crop((tx, ty, tx+tw, ty+th))
                    tile_img.save(img_dst / f"{tile_id}{ipath.suffix.lower()}")
                    write_yolo_rows(lbl_dst / f"{tile_id}.txt", tile_rows)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tile-size", type=int, default=640)
    parser.add_argument("--overlap", type=int, default=160)
    args = parser.parse_args()
    
    project_root = resolve_project_root()
    src_data = project_root / "data" 
    dst_data = project_root / "data_saft"
    
    process_split("train", src_data, dst_data, args.tile_size, args.overlap)
    process_split("val", src_data, dst_data, args.tile_size, args.overlap)
    
    # Create data_saft.yaml
    from common import dump_yaml, load_yaml
    base_yaml = load_yaml(project_root / "configs" / "dataset.yaml")
    base_yaml["path"] = str(dst_data.resolve())
    base_yaml["train"] = "train/images"
    base_yaml["val"] = "val/images"
    dump_yaml(project_root / "configs" / "dataset_saft.yaml", base_yaml)

if __name__ == "__main__":
    main()
