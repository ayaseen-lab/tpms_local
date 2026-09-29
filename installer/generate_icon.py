"""Create a polished Fyrqom-branded app icon for the Windows exe and installer."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEST = Path(__file__).resolve().parent / "tpms_suite.ico"
PREVIEW = Path(__file__).resolve().parent / "tpms_suite.png"
SOURCE_PNG = Path(__file__).resolve().parents[1] / "assets" / "fyrqom_tpms_icon_source.png"

CHARCOAL = (16, 16, 17, 255)  # #101011
TEAL = (0, 211, 191, 255)  # #00d3bf
TEAL_DIM = (0, 160, 145, 255)
PAPER = (251, 251, 251, 255)
RING = (42, 52, 51, 255)

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_brand_mark(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(1, size // 18)
    radius = max(3, size // 6)
    draw.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=radius,
        fill=CHARCOAL,
    )

    cx = cy = size / 2
    outer = size * 0.34
    ring_w = max(2.0, size * 0.075)

    if size >= 48:
        draw.ellipse(
            [cx - outer - ring_w, cy - outer - ring_w, cx + outer + ring_w, cy + outer + ring_w],
            outline=(*TEAL[:3], 55),
            width=max(1, size // 48),
        )

    draw.ellipse(
        [cx - outer, cy - outer, cx + outer, cy + outer],
        outline=TEAL,
        width=max(2, int(round(ring_w))),
    )
    inner = outer - ring_w * 1.35
    if inner > 2:
        draw.ellipse(
            [cx - inner, cy - inner, cx + inner, cy + inner],
            outline=RING,
            width=max(1, size // 32),
        )

    if size >= 48:
        for deg in (0, 45, 90, 135, 180, 225, 270, 315):
            rad = math.radians(deg)
            r0, r1 = outer - ring_w * 0.15, outer + ring_w * 0.55
            x0 = cx + r0 * math.cos(rad)
            y0 = cy + r0 * math.sin(rad)
            x1 = cx + r1 * math.cos(rad)
            y1 = cy + r1 * math.sin(rad)
            draw.line([(x0, y0), (x1, y1)], fill=TEAL_DIM, width=max(1, size // 64))

    if size >= 32:
        tip = (cx + outer * 0.55, cy - outer * 0.35)
        draw.line([(cx, cy), tip], fill=TEAL, width=max(2, size // 28))
        hub = max(2, size // 28)
        draw.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=PAPER)

    letter = "F"
    font = _font(max(8, int(size * (0.42 if size < 48 else 0.28))))
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1]
    if size >= 48:
        ty += size * 0.18
        draw.text((tx, ty), letter, fill=PAPER, font=font)
    else:
        draw.text((tx, ty), letter, fill=TEAL, font=font)

    if size >= 64:
        img = img.filter(ImageFilter.SMOOTH_MORE)
    return img


def _compose_from_source(size: int) -> Image.Image | None:
    if not SOURCE_PNG.is_file():
        return None
    try:
        src = Image.open(SOURCE_PNG).convert("RGBA")
    except Exception:
        return None

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    pad = max(1, size // 18)
    radius = max(3, size // 6)
    draw.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=radius,
        fill=CHARCOAL,
    )
    inset = max(2, size // 12)
    box = size - inset * 2
    fitted = src.copy()
    fitted.thumbnail((box, box), Image.Resampling.LANCZOS)
    ox = (size - fitted.width) // 2
    oy = (size - fitted.height) // 2
    canvas.alpha_composite(fitted, (ox, oy))
    return canvas


def main() -> None:
    # Build each face ourselves, then pack a proper multi-size ICO.
    faces: list[Image.Image] = []
    for w, h in SIZES:
        if w >= 128:
            face = _compose_from_source(w) or _draw_brand_mark(w)
        else:
            face = _draw_brand_mark(w)
        faces.append(face.convert("RGBA"))

    # Pillow ICO writer: pass the largest image + explicit sizes list.
    # Writing via save(..., append_images=...) often drops all but 16x16.
    master = faces[-1]
    master.save(DEST, format="ICO", sizes=SIZES)
    # Re-open and verify; if only one frame, rewrite with a custom approach.
    check = Image.open(DEST)
    n = getattr(check, "n_frames", 1)
    check.close()
    if n < 3:
        # Manual multi-size write: save PNG frames into ICO via Pillow's IcoImagePlugin path.
        # Use the first image as container and force sizes by saving from a dedicated list.
        tmp = DEST.with_suffix(".tmp.ico")
        # Create a square master and let Pillow generate each requested size from it.
        # Also write each custom face by building an ICO with ImageMagick-like packing:
        from io import BytesIO
        import struct

        def _png_bytes(im: Image.Image) -> bytes:
            buf = BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()

        entries = []
        blobs = []
        offset = 6 + 16 * len(faces)
        for face in faces:
            blob = _png_bytes(face)
            w, h = face.size
            entries.append((w if w < 256 else 0, h if h < 256 else 0, len(blob), offset))
            blobs.append(blob)
            offset += len(blob)

        with tmp.open("wb") as fh:
            fh.write(struct.pack("<HHH", 0, 1, len(faces)))
            for w, h, size, off in entries:
                # width, height, colors, reserved, planes, bitcount, bytes, offset
                fh.write(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, size, off))
            for blob in blobs:
                fh.write(blob)
        tmp.replace(DEST)

    faces[-1].save(PREVIEW, format="PNG")
    verify = Image.open(DEST)
    print(f"Wrote {DEST} ({DEST.stat().st_size} bytes, frames={getattr(verify, 'n_frames', 1)})")
    verify.close()
    print(f"Wrote {PREVIEW}")


if __name__ == "__main__":
    main()
