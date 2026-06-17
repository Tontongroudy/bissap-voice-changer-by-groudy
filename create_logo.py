"""Génère bissap.ico — logo de Bissap Voice Changer by Groudy."""
from PIL import Image, ImageDraw, ImageFont
import math, os

SIZES = [256, 128, 64, 48, 32, 16]

# Palette bissap (couleur hibiscus : rouge-violet profond)
BG_OUTER   = (22,  4, 40)    # presque noir-violet
BG_INNER   = (110, 10, 80)   # violet-cramoisi
ACCENT     = (195, 20, 110)  # rose-magenta vif
GOLD       = (255, 200, 80)  # doré léger pour le texte principal
WHITE      = (255, 255, 255)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Fond circulaire dégradé simulé par cercles concentriques ───
    for r in range(size // 2, 0, -1):
        t = r / (size / 2)                # 1 au centre, 0 au bord
        ri = int(BG_OUTER[0] * t + BG_INNER[0] * (1 - t))
        gi = int(BG_OUTER[1] * t + BG_INNER[1] * (1 - t))
        bi = int(BG_OUTER[2] * t + BG_INNER[2] * (1 - t))
        cx, cy = size // 2, size // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(ri, gi, bi, 255))

    # ── Cercle accent (bord intérieur lumineux) ──────────────────
    bw = max(2, size // 30)
    m = max(2, size // 16)
    draw.ellipse([m, m, size - m, size - m], outline=ACCENT, width=bw)

    # ── Grande lettre "B" centrée ────────────────────────────────
    font_size_b = int(size * 0.52)
    font_b = None
    for path in [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]:
        if os.path.exists(path):
            try:
                font_b = ImageFont.truetype(path, font_size_b)
                break
            except Exception:
                continue
    if font_b is None:
        font_b = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "B", font=font_b)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] - size // 14

    # Ombre légère
    draw.text((tx + max(1, size // 64), ty + max(1, size // 64)), "B",
              font=font_b, fill=(0, 0, 0, 160))
    draw.text((tx, ty), "B", font=font_b, fill=GOLD)

    # ── Texte "BISSAP" en bas ────────────────────────────────────
    if size >= 48:
        font_size_s = max(8, int(size * 0.13))
        font_s = None
        for path in [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]:
            if os.path.exists(path):
                try:
                    font_s = ImageFont.truetype(path, font_size_s)
                    break
                except Exception:
                    continue
        if font_s is None:
            font_s = ImageFont.load_default()

        label = "BISSAP"
        bbox2 = draw.textbbox((0, 0), label, font=font_s)
        lw = bbox2[2] - bbox2[0]
        lx = (size - lw) // 2 - bbox2[0]
        ly = size - int(size * 0.22)
        draw.text((lx, ly), label, font=font_s, fill=WHITE)

    return img


def main():
    base = draw_icon(256)
    icon_images = [base.resize((s, s), Image.LANCZOS) for s in SIZES]

    out = os.path.join(os.path.dirname(__file__), "bissap.ico")
    icon_images[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=icon_images[1:],
    )
    print(f"Icône créée : {out}")

    # Aussi PNG 256 pour prévisualisation
    png_out = out.replace(".ico", ".png")
    base.save(png_out, format="PNG")
    print(f"Preview PNG  : {png_out}")


if __name__ == "__main__":
    main()
