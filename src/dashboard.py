from __future__ import annotations

import math
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from cloud_sync import fetch_recent_detections

ROOT_DIR = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT_DIR / "data" / "processed" / "detections.csv"
TARGET_LOCALIZATION_M = 20.0
load_dotenv(ROOT_DIR / ".env")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_mock_map(df: pd.DataFrame) -> pd.DataFrame:
    center_lat = float(os.getenv("SKYLINK_DEMO_CENTER_LAT", "26.3073"))
    center_lon = float(os.getenv("SKYLINK_DEMO_CENTER_LON", "50.1456"))
    step = float(os.getenv("SKYLINK_DEMO_STEP_DEG", "0.00022"))
    points = []
    for i, row in enumerate(df.itertuples(index=False)):
        radius = step * (1 + (i // 8) * 0.55)
        angle_deg = (i * 37) % 360
        angle_rad = math.radians(angle_deg)
        lat = center_lat + radius * math.sin(angle_rad)
        lon = center_lon + radius * math.cos(angle_rad)
        points.append(
            {
                "image_name": getattr(row, "image_name", f"image_{i + 1}"),
                "severity": getattr(row, "severity", "Unknown"),
                "lat": round(lat, 7),
                "lon": round(lon, 7),
                "gps_source": "mock",
            }
        )
    return pd.DataFrame(points)


def load_detections_from_supabase() -> pd.DataFrame:
    try:
        records = fetch_recent_detections(limit=300)
    except Exception:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if df.empty:
        return df
    numeric_columns = [
        "detection_count",
        "max_confidence",
        "gps_lat",
        "gps_lon",
        "localization_m",
        "processing_seconds",
        "estimated_accuracy",
    ]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_detections(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    numeric_columns = [
        "detection_count",
        "max_confidence",
        "gps_lat",
        "gps_lon",
        "localization_m",
        "processing_seconds",
        "estimated_accuracy",
    ]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _map_palette(severity: str) -> str:
    return "#FF4B4B" if severity == "High Severity" else "#FFC857"


def build_map_points(df: pd.DataFrame) -> pd.DataFrame:
    has_gps_columns = {"gps_lat", "gps_lon"}.issubset(df.columns)
    real_points = df.dropna(subset=["gps_lat", "gps_lon"]).copy() if has_gps_columns else pd.DataFrame()
    if not real_points.empty:
        map_df = pd.DataFrame(
            {
                "image_name": real_points.get("image_name", "unknown"),
                "severity": real_points.get("severity", "Unknown"),
                "lat": real_points["gps_lat"],
                "lon": real_points["gps_lon"],
                "gps_source": "gps",
            }
        )
    elif _bool_env("SKYLINK_DEMO_GPS_IF_MISSING", True) and not df.empty:
        map_df = build_mock_map(df)
    else:
        return pd.DataFrame()

    map_df["marker_color"] = map_df["severity"].astype(str).apply(_map_palette)
    return map_df


def render_map(df: pd.DataFrame) -> pd.DataFrame:
    map_df = build_map_points(df)
    if map_df.empty:
        st.info("No GPS geo-tags available yet.")
        return map_df

    if (map_df["gps_source"] == "mock").all():
        st.warning("Live GPS is unavailable. Showing realistic demo coordinates for presentation.")

    st.map(
        map_df,
        latitude="lat",
        longitude="lon",
        color="marker_color",
        size=8,
        zoom=17,
        height=430,
    )
    return map_df


def render_location_index(map_df: pd.DataFrame) -> None:
    if map_df.empty:
        return
    st.subheader("Location Index")
    location_df = map_df.copy()
    location_df["google_maps"] = location_df.apply(
        lambda row: f"https://www.google.com/maps?q={row['lat']:.7f},{row['lon']:.7f}", axis=1
    )
    location_df["lat"] = location_df["lat"].map(lambda v: f"{float(v):.7f}")
    location_df["lon"] = location_df["lon"].map(lambda v: f"{float(v):.7f}")

    st.dataframe(
        location_df[["image_name", "severity", "gps_source", "lat", "lon", "google_maps"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "image_name": st.column_config.TextColumn("Image"),
            "severity": st.column_config.TextColumn("Severity"),
            "gps_source": st.column_config.TextColumn("Source"),
            "lat": st.column_config.TextColumn("Latitude"),
            "lon": st.column_config.TextColumn("Longitude"),
            "google_maps": st.column_config.LinkColumn("Navigate", display_text="Open in Google Maps"),
        },
    )


def render_images(df: pd.DataFrame) -> None:
    if "timestamp_utc" in df.columns:
        df = df.sort_values(by="timestamp_utc", ascending=False)
    st.subheader("Latest Detections")
    shown = 0
    for _, row in df.iterrows():
        image_url = str(row.get("image_url", "")).strip()
        local_path = str(row.get("processed_path", "")).strip()
        caption = f"{row.get('image_name', 'unknown')} | {row.get('severity', 'Unknown')}"
        if image_url.startswith("http"):
            st.image(image_url, caption=caption, width="stretch")
            shown += 1
        elif local_path:
            image_file = Path(local_path)
            if image_file.exists():
                st.image(str(image_file), caption=caption, width="stretch")
                shown += 1
        else:
            continue

        if shown >= 8:
            break
    if shown == 0:
        st.info("No processed images found in `data/processed`.")


def render_flight_equations() -> None:
    st.subheader("Technical Grounding (Optional)")
    rho = st.number_input("Air density rho (kg/m^3)", min_value=0.5, max_value=2.0, value=1.225, step=0.01)
    c_d = st.number_input("Drag coefficient C_D", min_value=0.1, max_value=2.0, value=1.1, step=0.05)
    area = st.number_input("Frontal area A (m^2)", min_value=0.001, max_value=1.0, value=0.04, step=0.001)
    wind = st.number_input("Wind speed V (m/s)", min_value=0.0, max_value=20.0, value=7.0, step=0.1)
    thrust = st.number_input("Total thrust T (N)", min_value=0.0, max_value=200.0, value=20.0, step=0.1)
    weight = st.number_input("Weight W (N)", min_value=0.1, max_value=200.0, value=9.0, step=0.1)

    drag_force = 0.5 * rho * c_d * area * (wind**2)
    tw_ratio = thrust / weight

    st.latex(r"F_D = \frac{1}{2}\rho C_D A V^2")
    st.metric("Drag Force (N)", f"{drag_force:.3f}")
    st.metric("Thrust/Weight Ratio", f"{tw_ratio:.3f}")
    st.caption("Safety target: T/W >= 2.0")


def main() -> None:
    st.set_page_config(page_title="SkyLink MVP Dashboard", layout="wide")
    st.title("SkyLink MVP Dashboard")
    st.caption("Crack detection, GPS localization, and severity triage for drone imagery.")

    has_supabase_config = bool(os.getenv("SUPABASE_DB_POOLER_URL") or os.getenv("SUPABASE_DB_URL"))
    df = load_detections_from_supabase() if has_supabase_config else pd.DataFrame()
    data_source = "Supabase" if not df.empty else "Local CSV"
    if df.empty:
        df = load_detections(CSV_PATH)

    if df.empty:
        st.warning("No detections found. Run `python src/main.py` first.")
        render_flight_equations()
        return

    st.caption(f"Data source: {data_source}")

    total = int(df["detection_count"].sum()) if "detection_count" in df.columns else 0
    high_severity = int((df.get("severity", "") == "High Severity").sum()) if "severity" in df.columns else 0
    avg_conf = float(df["max_confidence"].mean()) if "max_confidence" in df.columns else 0.0
    avg_localization = float(df["localization_m"].mean()) if "localization_m" in df.columns else float("nan")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Detections", f"{total}")
    c2.metric("High Severity", f"{high_severity}")
    c3.metric("Average Confidence", f"{avg_conf:.2f}")
    if avg_localization == avg_localization:  # NaN check
        c4.metric("Localization Error (m)", f"{avg_localization:.1f}")
    else:
        c4.metric("Localization Error (m)", "N/A")

    st.subheader("Geo-tagged Detection Map")
    map_df = render_map(df)
    st.caption(f"Localization target: <= {TARGET_LOCALIZATION_M:.0f} m")
    render_location_index(map_df)

    render_images(df)
    render_flight_equations()


if __name__ == "__main__":
    main()
