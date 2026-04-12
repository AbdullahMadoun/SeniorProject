# Training Pilot Status

## Dataset

- Total images: 187
- Splits: train=149, val=18, test=20
- Converted boxes: 694
- Negative images: 21
- Source classes: ['alligator_crack', 'crack ', 'pothole ']

## Offline Augmentation

- Source train images augmented: 132
- Horizontal flips created: 132
- Brightness/blur variants created: 132

## Training Runs

### yolo12s_custom

- Run dir: `/opt/skylink-training-pilot/workspace/runs/yolo12s_custom`
- Best checkpoint: `/opt/skylink-training-pilot/workspace/runs/yolo12s_custom/weights/best.pt`
- Latest epoch: 2
- mAP50: 0.40694
- Precision: 0.56047
- Recall: 0.35484
- Train box loss: 1.50606
- Val box loss: 1.46812

### yolov8m_custom

- Run dir: `/opt/skylink-training-pilot/workspace/runs/yolov8m_custom`
- Best checkpoint: `/opt/skylink-training-pilot/workspace/runs/yolov8m_custom/weights/best.pt`
- Latest epoch: 2
- mAP50: 0.3639
- Precision: 0.40707
- Recall: 0.41935
- Train box loss: 1.63576
- Val box loss: 1.48176
