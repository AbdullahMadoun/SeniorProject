from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class DummyDetection:
    frame_id: str
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    confidence: float
    label: str = "pothole"


class DummyYoloPotholeDetector:
    def __init__(self, *, output_dir: Path) -> None:
        self.output_dir = output_dir

    def infer(self, frame_ids: Iterable[str]) -> list[DummyDetection]:
        detections: list[DummyDetection] = []
        for index, frame_id in enumerate(frame_ids):
            detections.append(
                DummyDetection(
                    frame_id=str(frame_id),
                    x_min=40 + (index * 5),
                    y_min=55 + (index * 4),
                    x_max=180 + (index * 5),
                    y_max=145 + (index * 4),
                    confidence=0.82,
                )
            )
        return detections

    def write_csv(self, detections: list[DummyDetection]) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.output_dir / "pothole_detections.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["frame_id", "label", "confidence", "x_min", "y_min", "x_max", "y_max"],
            )
            writer.writeheader()
            for detection in detections:
                writer.writerow(asdict(detection))
        return csv_path

    def run(self, frame_ids: Iterable[str]) -> dict[str, object]:
        detections = self.infer(frame_ids)
        csv_path = self.write_csv(detections)
        summary = {
            "detection_count": len(detections),
            "csv_path": str(csv_path),
            "detections": [asdict(item) for item in detections],
        }
        (self.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dummy YOLO pothole detector stub")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frame-id", action="append", dest="frame_ids", required=False)
    return parser


def main(argv: list[str] | None = None) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(argv)
    detector = DummyYoloPotholeDetector(output_dir=args.output_dir)
    frame_ids = args.frame_ids or ["frame-0001", "frame-0002", "frame-0003"]
    result = detector.run(frame_ids)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
