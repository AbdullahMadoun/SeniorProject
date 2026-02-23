from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT_DIR / "data" / "processed" / "detections.csv"


def add_mock_gps(
    csv_path: Path,
    center_lat: float,
    center_lon: float,
    radius_deg: float,
    seed: int,
    overwrite: bool,
) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing CSV: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError("detections.csv is empty.")

    rng = random.Random(seed)
    for idx in df.index:
        has_gps = pd.notna(df.at[idx, "gps_lat"]) and pd.notna(df.at[idx, "gps_lon"])
        if has_gps and not overwrite:
            continue

        lat = center_lat + rng.uniform(-radius_deg, radius_deg)
        lon = center_lon + rng.uniform(-radius_deg, radius_deg)
        df.at[idx, "gps_lat"] = round(lat, 7)
        df.at[idx, "gps_lon"] = round(lon, 7)

    df.to_csv(csv_path, index=False)
    safe_path = str(csv_path).encode("ascii", "backslashreplace").decode("ascii")
    print(f"Updated GPS in {safe_path}")
    print(f"Rows: {len(df)} | Center: ({center_lat}, {center_lon}) | Radius(deg): {radius_deg}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inject mock GPS coordinates into detections.csv")
    parser.add_argument("--csv", type=Path, default=CSV_PATH, help="Path to detections.csv")
    parser.add_argument("--center-lat", type=float, required=True, help="Center latitude")
    parser.add_argument("--center-lon", type=float, required=True, help="Center longitude")
    parser.add_argument(
        "--radius-deg",
        type=float,
        default=0.0008,
        help="Random jitter radius in degrees (~0.0001 ~= 11m latitude)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing GPS values")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    add_mock_gps(
        csv_path=args.csv,
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        radius_deg=args.radius_deg,
        seed=args.seed,
        overwrite=args.overwrite,
    )
