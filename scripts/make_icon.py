"""Draw packaging/icon.png (256x256): uv run scripts/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# rounded tile with a vertical gradient
tile = Image.new("RGBA", (S, S))
td = ImageDraw.Draw(tile)
for y in range(S):
    t = y / (S - 1)
    td.line([(0, y), (S, y)], fill=(int(70 + 60 * t), int(50 + 20 * t), int(200 - 60 * t), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=56, fill=255)
img.paste(tile, (0, 0), mask)
# speech bubble
d.rounded_rectangle([44, 58, 212, 170], radius=34, fill=(255, 255, 255, 240))
d.polygon([(88, 165), (76, 206), (126, 168)], fill=(255, 255, 255, 240))
# three "thinking" dots
for i, x in enumerate((92, 128, 164)):
    d.ellipse([x - 13, 101, x + 13, 127], fill=(90 + i * 30, 70, 220, 255))
out = Path(__file__).resolve().parent.parent / "packaging" / "icon.png"
img.save(out)
print("wrote", out)
