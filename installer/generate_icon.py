"""Create a simple app icon for the Windows exe and installer."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEST = Path(__file__).resolve().parent / "tpms_suite.ico"


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (15, 118, 110, 255))
        draw = ImageDraw.Draw(img)
        margin = max(1, size // 16)
        draw.rounded_rectangle(
            [margin, margin, size - margin - 1, size - margin - 1],
            radius=max(2, size // 8),
            outline=(255, 255, 255, 230),
            width=max(1, size // 24),
        )
        text = "T" if size < 32 else "TP"
        try:
            font = ImageFont.truetype("segoeui.ttf", max(8, int(size * 0.42)))
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size - tw) / 2, (size - th) / 2 - bbox[1]), text, fill="white", font=font)
        images.append(img)
    images[0].save(DEST, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"Wrote {DEST}")


if __name__ == "__main__":
    main()
