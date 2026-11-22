"""アプリアイコン（1024×1024）を作る。アイボリー × 墨色 + 朱 1 点。

ルーペの輪と、その中央に拾った色の点。引き算だけで作る。
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "Resources" / "Assets.xcassets" / "AppIcon.appiconset"

SIZE = 1024
SCALE = 4
PAPER = (249, 248, 245)
INK = (26, 26, 27)
ACCENT = (180, 71, 42)


def main() -> None:
    canvas = SIZE * SCALE
    image = Image.new("RGB", (canvas, canvas), PAPER)
    draw = ImageDraw.Draw(image)

    cx = cy = canvas / 2
    ring_radius = 0.293 * canvas
    ring_width = 0.062 * canvas
    draw.ellipse(
        [cx - ring_radius, cy - ring_radius, cx + ring_radius, cy + ring_radius],
        outline=INK,
        width=int(ring_width),
    )

    dot_radius = 0.104 * canvas
    draw.ellipse([cx - dot_radius, cy - dot_radius, cx + dot_radius, cy + dot_radius], fill=ACCENT)

    icon = image.resize((SIZE, SIZE), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    icon.save(OUT / "AppIcon.png", "PNG")
    print(f"wrote {OUT / 'AppIcon.png'} ({icon.size})")


if __name__ == "__main__":
    main()
