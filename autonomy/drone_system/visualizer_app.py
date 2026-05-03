from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pydeck as pdk
import streamlit as st


AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
if str(AUTONOMY_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_ROOT))


DEFAULT_CSV = AUTONOMY_ROOT.parent / "artifacts" / "synthetic_telemetry_log.csv"


def _load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"frame", "timestamp", "lat", "lon", "alt"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Telemetry CSV missing columns: {sorted(missing)}")
    df["frame"] = pd.to_numeric(df["frame"], errors="coerce")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["alt"] = pd.to_numeric(df["alt"], errors="coerce")
    df = df.dropna(subset=["frame", "lat", "lon", "alt"]).reset_index(drop=True)
    return df


def _trajectory_deck(df: pd.DataFrame) -> pdk.Deck:
    path_points = [[float(row.lon), float(row.lat), float(row.alt)] for row in df.itertuples(index=False)]
    line_layer = pdk.Layer(
        "PathLayer",
        [{"path": path_points, "name": "Mission Path"}],
        get_path="path",
        get_width=6,
        width_scale=1,
        width_min_pixels=3,
        get_color=[227, 76, 38],
        pickable=True,
    )
    points_layer = pdk.Layer(
        "ScatterplotLayer",
        df,
        get_position="[lon, lat]",
        get_radius=2,
        radius_min_pixels=4,
        get_fill_color=[45, 212, 191],
        pickable=True,
    )
    view_state = pdk.ViewState(
        latitude=float(df["lat"].mean()),
        longitude=float(df["lon"].mean()),
        zoom=17,
        pitch=55,
        bearing=20,
    )
    return pdk.Deck(
        map_style="mapbox://styles/mapbox/light-v10",
        initial_view_state=view_state,
        layers=[line_layer, points_layer],
        tooltip={"text": "Mission trajectory"},
    )


def main() -> None:
    st.set_page_config(page_title="Drone Mission Visualizer", layout="wide")
    st.title("Drone Mission Visualizer")
    st.caption("Phase 0 baseline visualizer for mission controls and telemetry replay.")

    csv_default = str(DEFAULT_CSV if DEFAULT_CSV.exists() else "")
    csv_path = Path(st.text_input("Telemetry CSV", value=csv_default).strip()) if csv_default else None

    if csv_path is None or not csv_path.exists():
        st.warning("Telemetry CSV not found yet. Generate one first with the synthetic telemetry script.")
        return

    df = _load_csv(csv_path)
    if df.empty:
        st.warning("Telemetry CSV is empty after parsing.")
        return

    last = df.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Frames", f"{len(df)}")
    c2.metric("Start Altitude (m)", f"{df.iloc[0]['alt']:.1f}")
    c3.metric("End Altitude (m)", f"{last['alt']:.1f}")
    c4.metric("Latitude Span", f"{(df['lat'].max() - df['lat'].min()) * 111000:.1f} m")

    st.subheader("3D Trajectory Preview")
    st.pydeck_chart(_trajectory_deck(df), use_container_width=True)

    st.subheader("Replay Cursor")
    frame_index = int(
        st.slider("Frame", min_value=0, max_value=max(len(df) - 1, 0), value=min(10, len(df) - 1), step=1)
    )
    current = df.iloc[frame_index]

    c5, c6, c7 = st.columns(3)
    c5.metric("Frame", f"{int(current['frame'])}")
    c6.metric("Latitude", f"{current['lat']:.7f}")
    c7.metric("Longitude", f"{current['lon']:.7f}")
    st.caption(f"Timestamp: {current['timestamp']} | Altitude: {current['alt']:.2f} m")

    st.subheader("Telemetry Table")
    st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
