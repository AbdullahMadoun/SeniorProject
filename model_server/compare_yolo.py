import cv2
import os
from ultralytics import YOLO

# Classes map
cls_map = {
    0: "D00 Longitudinal",
    1: "D10 Transverse",
    2: "D20 Alligator",
    3: "D40 Pothole",
    4: "Repair",
}

def draw_boxes(img, results, title):
    img_copy = img.copy()
    for r in results:
        boxes = r.boxes
        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            label = f"{cls_map.get(cls_id, str(cls_id))} {conf:.2f}"
            
            # Draw box
            cv2.rectangle(img_copy, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(img_copy, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
    cv2.putText(img_copy, title, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    return img_copy

from huggingface_hub import hf_hub_download

print("Loading Models...")
yolo12_path = hf_hub_download(repo_id="rezzzq/yolo12s-road-damage-rdd2022", filename="yolo12s_RDD2022_best.pt")
model_v12 = YOLO(yolo12_path)
model_v8 = YOLO("/root/oracl4_rdd/models/YOLOv8_Small_RDD.pt")

img_dir = "/root/test_images/Raw images/RGB main"
out_dir = "/root/road_inspector/test_outputs"
test_images = ["image100.jpg", "image50.jpg", "image167.jpg"]

for img_name in test_images:
    path = os.path.join(img_dir, img_name)
    if not os.path.exists(path): continue
    
    print(f"Testing {img_name}")
    img = cv2.imread(path)
    
    # Run YOLOv12
    res_v12 = model_v12(img, conf=0.25)
    img_v12 = draw_boxes(img, res_v12, "YOLOv12s (rezzzq)")
    
    # Run YOLOv8
    res_v8 = model_v8(img, conf=0.25)
    img_v8 = draw_boxes(img, res_v8, "YOLOv8s (oracl4)")
    
    # Concatenate horizontally
    hconcat = cv2.hconcat([img_v12, img_v8])
    
    out_path = os.path.join(out_dir, f"compare_{img_name}")
    cv2.imwrite(out_path, hconcat)
    print(f"Saved {out_path}")

print("Done.")
