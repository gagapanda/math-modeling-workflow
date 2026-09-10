#!/usr/bin/env python3
"""Create bounded JPEG previews for context-safe visual review."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps


def preview_image(source: Path, target: Path, max_width: int, quality: int) -> tuple[int, int, int]:
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if image.width > max_width:
            height = round(image.height * max_width / image.width)
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="JPEG", quality=quality, optimize=True, progressive=True)
        return image.width, image.height, target.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-width", type=int, default=800)
    parser.add_argument("--quality", type=int, default=72)
    args = parser.parse_args()
    if args.max_width < 320:
        parser.error("--max-width must be at least 320")
    if not 1 <= args.quality <= 95:
        parser.error("--quality must be between 1 and 95")
    if not args.input_dir.is_dir():
        parser.error(f"input directory does not exist: {args.input_dir}")

    sources = sorted(args.input_dir.glob("page-*.png"))
    if not sources:
        parser.error(f"no page-*.png files found in {args.input_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for source in sources:
        target = args.output_dir / f"{source.stem}.jpg"
        width, height, size = preview_image(source, target, args.max_width, args.quality)
        total += size
        print(f"{source.name} -> {target.name}: {width}x{height}, {size} bytes")
    print(f"created={len(sources)} total_bytes={total} output_dir={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
