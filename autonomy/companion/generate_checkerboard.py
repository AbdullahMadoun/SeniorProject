from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_checkerboard_svg(
    *,
    inner_corners_cols: int,
    inner_corners_rows: int,
    square_size_mm: float,
    margin_mm: float,
) -> str:
    squares_x = inner_corners_cols + 1
    squares_y = inner_corners_rows + 1
    width_mm = (squares_x * square_size_mm) + (2 * margin_mm)
    height_mm = (squares_y * square_size_mm) + (2 * margin_mm)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="{height_mm}mm" viewBox="0 0 {width_mm} {height_mm}">',
        f'<rect x="0" y="0" width="{width_mm}" height="{height_mm}" fill="white"/>',
    ]
    for row in range(squares_y):
        for col in range(squares_x):
            fill = "black" if (row + col) % 2 == 0 else "white"
            x = margin_mm + (col * square_size_mm)
            y = margin_mm + (row * square_size_mm)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{square_size_mm}" height="{square_size_mm}" fill="{fill}"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def generate_checkerboard(
    *,
    output_dir: Path,
    inner_corners_cols: int = 9,
    inner_corners_rows: int = 6,
    square_size_mm: float = 24.0,
    margin_mm: float = 12.0,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / "checkerboard.svg"
    metadata_path = output_dir / "checkerboard.json"
    svg = build_checkerboard_svg(
        inner_corners_cols=inner_corners_cols,
        inner_corners_rows=inner_corners_rows,
        square_size_mm=square_size_mm,
        margin_mm=margin_mm,
    )
    svg_path.write_text(svg, encoding="utf-8")
    metadata = {
        "inner_corners_cols": inner_corners_cols,
        "inner_corners_rows": inner_corners_rows,
        "square_size_mm": square_size_mm,
        "margin_mm": margin_mm,
        "svg_path": str(svg_path),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a printable checkerboard calibration target")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cols", type=int, default=9)
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--square-size-mm", type=float, default=24.0)
    parser.add_argument("--margin-mm", type=float, default=12.0)
    return parser


def main(argv: list[str] | None = None) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = generate_checkerboard(
        output_dir=args.output_dir,
        inner_corners_cols=args.cols,
        inner_corners_rows=args.rows,
        square_size_mm=args.square_size_mm,
        margin_mm=args.margin_mm,
    )
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()

