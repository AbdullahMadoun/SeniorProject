import base64, json, requests, os, time

API_URL = 'http://localhost:17612'
API_KEY = 'road-inspector-secret-key-2024'
IMG_DIR = '/root/test_images/Raw images/RGB main'
OUT_DIR = '/root/road_inspector/test_outputs/dual_yolo_run'

os.makedirs(OUT_DIR, exist_ok=True)

test_images = [
    'image1.jpg', 'image10.jpg', 'image101.jpg', 'image102.jpg', 
    'image103.jpg', 'image104.jpg', 'image105.jpg', 'image11.jpg', 
    'image110.jpg', 'image111.jpg'
]

print("Starting Dual YOLO + VLM pipeline evaluation on 10 new images...\n")

for img_name in test_images:
    path = os.path.join(IMG_DIR, img_name)
    if not os.path.exists(path):
        print(f"Skipping {img_name}, file not found.")
        continue
    
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    
    print(f'=== Testing Dual YOLO+VLM on {img_name} ===')
    t0 = time.time()
    try:
        resp = requests.post(f'{API_URL}/analyze',
            json={'image_b64': b64, 'location': {'lat': 26.305, 'lon': 50.146}},
            headers={'X-API-Key': API_KEY}, timeout=300)
        elapsed = time.time() - t0
        
        if resp.status_code == 200:
            data = resp.json()
            report = data['report']
            print(f'  Status: 200 OK | Inference Time: {elapsed:.1f}s')
            print(f'  Summary: {report.get("summary", "")}')
            
            # Load original image locally to draw boxes
            import cv2
            import numpy as np
            orig_img = cv2.imread(path)
            
            for box in report.get('boxes', []):
                b_id = box.get("id")
                b_lbl = box.get("label")
                b_sev = box.get("severity")
                b_xy = box.get("bbox_xyxy")
                
                print(f'    Box: {b_id} | {b_lbl} | Sev: {b_sev}')
                
                # Draw local rectangle
                if b_xy and len(b_xy) == 4:
                    x1, y1, x2, y2 = b_xy
                    # Color based on severity
                    color = (0, 0, 255) # High = Red
                    if b_sev == "moderate": color = (0, 165, 255) # Orange
                    elif b_sev == "low": color = (0, 255, 0) # Green
                    
                    cv2.rectangle(orig_img, (x1, y1), (x2, y2), color, 6)
                    cv2.putText(orig_img, f"{b_id}: {b_sev}", (x1, y1 - 10), 
                                cv2.FONT_HERSHEY_DUPLEX, 1.2, color, 3)
            
            # Save client-annotated image
            out_img = os.path.join(OUT_DIR, f'dual_{img_name}')
            cv2.imwrite(out_img, orig_img)
            
            # Save markdown report
            out_md = os.path.join(OUT_DIR, f'dual_{img_name.replace(".jpg", ".md")}')
            with open(out_md, 'w') as f:
                f.write(report.get('report_markdown', ''))
                
        else:
            print(f'  Error {resp.status_code}: {resp.text[:200]} | Time: {elapsed:.1f}s')
    except Exception as e:
        print(f'  Request failed: {e}')
    print()

print(f"Evaluation complete. Results saved to {OUT_DIR}")
