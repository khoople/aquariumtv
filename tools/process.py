"""Turn raw SD output into Roku-ready images.

  python process.py           # build roku/images from tools/selection.json
  python process.py --sheets  # contact sheets of every candidate (with cutouts) for picking

selection.json picks which candidate to use and which way each fish faces in the
raw image. Anything not listed falls back to candidate 00 facing right.
"""
import argparse
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CUT = RAW / "cutouts"
OUT = HERE.parent / "roku" / "images"

SCREEN = (1920, 1080)
# Matches the background Poster in AquariumScene.xml: 5% overscan so it can drift.
BG_SIZE = (2016, 1134)
# Sprites are stored at their largest on-screen size (depth 1.0), plus a smaller
# copy used below depth FAR_SCALE, so the Roku never upscales and never shrinks
# a sprite by more than ~1.5x (big on-the-fly shrinks make fine detail shimmer).
FAR_SCALE = 0.7

# Where the sunlight in the background comes from, as a fraction of the screen
# (y < 0 is above the top edge). The rays layer is padded on both sides so it can
# sway around this point; keep in sync with the "rays" Group in AquariumScene.xml.
# Where the light rays fan out from, as a fraction of the screen: half a screen
# height above the top, near the centre. That's where the beams painted into
# the background converge, measured at the middle of the background drift. The rays
# Group's scaleRotateCenter in AquariumScene.xml and RAYS_PIVOT in render_preview.py
# are (SUN.x*1920 + RAYS_PAD, SUN.y*1080).
SUN = (0.47, -0.5)
# The painted beams' clusters as (degrees from straight down, relative strength),
# measured from SUN. Rays are drawn on these so the shimmer runs along them.
RAY_CLUSTERS = [(-25.1, 5.0), (-18.4, 15.8), (-7.8, 22.4), (3.8, 18.9), (17.3, 4.2), (23.6, 10.1)]
# Beams left of LEFT_SOFT_FROM degrees fade toward LEFT_SOFT of their brightness by
# LEFT_SOFT_AT degrees, so the left side stays softer than the bright centre.
LEFT_SOFT, LEFT_SOFT_FROM, LEFT_SOFT_AT = 0.45, -7.0, -25.0
# Overall strength of the rays (1 = as drawn).
RAY_GAIN = 0.8
RAYS_PAD = 90
RAYS_SIZE = (SCREEN[0] + 2 * RAYS_PAD, SCREEN[1])

# Furthest the foreground layer shifts up during the drift (the "foreground"
# interpolator in AquariumScene.xml). Decor must sink deeper than this or its
# cut-off base peeks above the bottom of the screen.
FG_PARALLAX_Y = 60

_session = None


def remove_bg(path):
    """Background removal with a cache, so re-running process.py is cheap."""
    global _session
    cached = CUT / f"{path.stem}.png"
    if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
        return Image.open(cached)
    from rembg import new_session, remove

    if _session is None:
        _session = new_session("birefnet-general")
    print(f"  cutting out {path.name}")
    img = remove(Image.open(path).convert("RGB"), session=_session)
    # Drop faint halo pixels left over from the white background.
    alpha = img.getchannel("A").point(lambda a: 0 if a < 24 else a)
    img.putalpha(alpha)
    CUT.mkdir(parents=True, exist_ok=True)
    img.save(cached)
    return img


def save_sprite(img, path):
    """Save an RGBA sprite as a palette PNG via libimagequant: about a third of
    the size, with no visible loss even on smooth gradients. Needed to keep the
    app under Roku's 4 MB limit (certification 3.7)."""
    try:
        import imagequant
        quantized = imagequant.quantize_pil_image(img, dithering_level=1.0, max_quality=95, min_quality=70)
    except (ImportError, RuntimeError):
        # Not installed, or 256 colours can't reach the quality floor for this
        # sprite: keep it full colour rather than degrade it.
        img.save(path, optimize=True)
        return
    quantized.save(path, optimize=True)


def cover(img, size):
    return ImageOps.fit(img, size, Image.LANCZOS, centering=(0.5, 0.5))


def contact_sheets():
    sheets = RAW / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    groups = {}
    for p in sorted([*(RAW / "fish").glob("*.png"), *(RAW / "decor").glob("*.png"),
                     *(RAW / "critters").glob("*.png")]):
        groups.setdefault(p.stem.rsplit("_", 1)[0], []).append(p)
    for fid, paths in groups.items():
        cell = 400
        sheet = Image.new("RGB", (cell * len(paths), cell * 2 + 30), (40, 40, 40))
        d = ImageDraw.Draw(sheet)
        for i, p in enumerate(paths):
            raw = Image.open(p).convert("RGB")
            raw.thumbnail((cell, cell))
            sheet.paste(raw, (i * cell, 30))
            cut = remove_bg(p)
            checker = Image.new("RGB", cut.size, (20, 70, 140))
            checker.paste(cut, mask=cut.getchannel("A"))
            checker.thumbnail((cell, cell))
            sheet.paste(checker, (i * cell, cell + 30))
            d.text((i * cell + 6, 6), p.stem, fill=(255, 255, 255), font=ImageFont.load_default(20))
        sheet.save(sheets / f"{fid}.jpg", quality=85)
        print(f"sheet {fid}")
    bgs = sorted((RAW / "background").glob("*.png"))
    if bgs:
        w = 640
        sheet = Image.new("RGB", (w * 2, (len(bgs) + 1) // 2 * 360), (40, 40, 40))
        for i, p in enumerate(bgs):
            sheet.paste(cover(Image.open(p).convert("RGB"), (w, 360)), (i % 2 * w, i // 2 * 360))
            ImageDraw.Draw(sheet).text((i % 2 * w + 6, i // 2 * 360 + 6), p.stem, fill="white",
                                       font=ImageFont.load_default(20))
        sheet.save(sheets / "background.jpg", quality=85)
        print("sheet background")


def bubble_sprite(size=64):
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2
    for r in range(int(c) - 2, 0, -1):
        # Mostly clear in the middle, brighter toward the rim, like a real bubble.
        t = r / c
        a = int(20 + 160 * t ** 6)
        d.ellipse((c - r, c - r, c + r, c + r), fill=(200, 235, 255, a))
    d.ellipse((s * 0.25, s * 0.2, s * 0.45, s * 0.38), fill=(255, 255, 255, 220))
    return img.resize((size, size), Image.LANCZOS)


def wedge(origin, angle, width, length=4000):
    """Triangle from origin, centred on angle (radians from straight down)."""
    ox, oy = origin
    a0, a1 = angle - width / 2, angle + width / 2
    return [(ox, oy), (ox + length * math.sin(a0), oy + length * math.cos(a0)),
            (ox + length * math.sin(a1), oy + length * math.cos(a1))]


def light_rays(layer, layers=3, seed=7):
    """One of several ray layers. Beams follow the clusters painted into the
    background (RAY_CLUSTERS), a few per cluster, plus some faint strays. They're
    shuffled and dealt round-robin into layers so each layer has some of every
    cluster; fading the layers out of phase makes individual beams flicker."""
    rng = random.Random(seed)
    # Drawn at half resolution; the scene stretches it to RAYS_SIZE.
    w, h = RAYS_SIZE[0] // 2, RAYS_SIZE[1] // 2
    origin = ((SUN[0] * SCREEN[0] + RAYS_PAD) / 2, SUN[1] * SCREEN[1] / 2)
    soft = Image.new("L", (w, h), 0)
    sharp = Image.new("L", (w, h), 0)
    ds, dt = ImageDraw.Draw(soft), ImageDraw.Draw(sharp)
    top = max(s for _, s in RAY_CLUSTERS)
    beams = []
    for deg, strength in RAY_CLUSTERS:
        k = (strength / top) ** 0.5
        for _ in range(2 + round(3 * k)):
            a = deg + rng.uniform(-1.6, 1.6)
            beams.append((a, int(rng.randint(60, 100) * (0.35 + 0.65 * k))))
    for _ in range(4):
        beams.append((rng.uniform(-31, 27), rng.randint(25, 40)))
    left = lambda a: 1 - (1 - LEFT_SOFT) * min(max((LEFT_SOFT_FROM - a) / (LEFT_SOFT_FROM - LEFT_SOFT_AT), 0), 1)
    beams = [(math.radians(a), int(b * left(a))) for a, b in beams]
    rng.shuffle(beams)
    for i, (angle, bright) in enumerate(beams):
        # Draw every beam's numbers so the layout is shared by all layers.
        width = math.radians(rng.uniform(0.6, 1.6))
        streaks = [(rng.uniform(-0.4, 0.4), math.radians(rng.uniform(0.05, 0.12)), rng.randint(35, 75))
                   for _ in range(2)]
        if i % layers != layer:
            continue
        ds.polygon(wedge(origin, angle, width), fill=bright)
        # Thin bright filaments inside the beam give it texture as it fades.
        for pos, sw, a in streaks:
            dt.polygon(wedge(origin, angle + pos * width, sw), fill=a)
    img = ImageChops.add(soft.filter(ImageFilter.GaussianBlur(12)), sharp.filter(ImageFilter.GaussianBlur(2)))
    # Fade beams out with distance from the sun, so they die off toward the sand.
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(xx - origin[0], yy - origin[1])
    near = -origin[1]
    fade = np.clip(1 - (dist - near) / (h * 0.85), 0, 1) ** 1.4
    alpha = Image.fromarray((np.asarray(img, dtype=float) * fade * RAY_GAIN).astype(np.uint8))
    size = (w, h)
    rays = Image.new("RGBA", size, (210, 240, 255, 0))
    rays.putalpha(alpha)
    return rays


def build(selection):
    cfg = json.loads((HERE / "assets.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)

    bg_name = selection.get("background", "bg_00")
    src = Image.open(RAW / "background" / f"{bg_name}.png").convert("RGB")
    cover(src, BG_SIZE).save(OUT / "background.jpg", quality=90, optimize=True)
    print(f"background <- {bg_name}")

    meta = []
    for f in cfg["fish"]:
        pick = selection.get("fish", {}).get(f["id"], {})
        src = RAW / "fish" / f"{pick.get('candidate', f['id'] + '_00')}.png"
        if not src.exists():
            print(f"skipping {f['id']}: {src.name} not generated")
            continue
        img = remove_bg(src)
        img = img.crop(img.getchannel("A").getbbox())
        if pick.get("facing", "right") == "left":
            img = ImageOps.mirror(img)
        # The shark always swims near the front, so it never needs the far copy.
        variants = (("", 1.0),) if f["kind"] == "shark" else (("", 1.0), ("_far", FAR_SCALE))
        for suffix, scale in variants:
            w = round(f["size"] * scale)
            h = round(img.height * w / img.width)
            sprite = img.resize((w, h), Image.LANCZOS)
            save_sprite(sprite, OUT / f"fish_{f['id']}_r{suffix}.png")
            save_sprite(ImageOps.mirror(sprite), OUT / f"fish_{f['id']}_l{suffix}.png")
        meta.append({"id": f["id"], "kind": f["kind"], "w": f["size"],
                     "h": round(f["size"] * img.height / img.width)})
        print(f"fish {f['id']} <- {src.stem}")
    (OUT / "fish.json").write_text(json.dumps(meta, indent=1))

    # Foreground decor: closer to the camera than any fish, so slightly darker,
    # bluer and softer (shallow depth of field) than the brightly lit tank.
    decor = []
    for d in cfg.get("decor", []):
        name = selection.get("decor", {}).get(d["id"], f"{d['id']}_00")
        src = RAW / "decor" / f"{name}.png"
        if not src.exists():
            print(f"skipping {d['id']}: {src.name} not generated")
            continue
        img = remove_bg(src)
        img = img.crop(img.getchannel("A").getbbox())
        if d.get("flip"):
            img = ImageOps.mirror(img)
        w = round(img.width * d["h"] / img.height)
        img = img.resize((w, d["h"]), Image.LANCZOS)
        rgb = ImageChops.multiply(img.convert("RGB"), Image.new("RGB", img.size, (175, 195, 215)))
        defocus = d.get("defocus", 1.2)
        rgb = rgb.filter(ImageFilter.GaussianBlur(defocus))
        alpha = img.getchannel("A").filter(ImageFilter.GaussianBlur(defocus))
        rgb.putalpha(alpha)
        save_sprite(rgb, OUT / f"fg_{d['id']}.png")
        sink = d["sink"]
        if sink < FG_PARALLAX_Y + 20:
            print(f"  {d['id']}: sink {sink} would show its base during the drift; using {FG_PARALLAX_Y + 20}")
            sink = FG_PARALLAX_Y + 20
        decor.append({"id": d["id"], "x": d["x"], "y": SCREEN[1] + sink - d["h"],
                      "w": w, "h": d["h"], "sway": d["sway"],
                      "swayPeriod": d.get("sway_period", 18), "bubbles": d.get("bubbles", 0)})
        print(f"decor {d['id']} <- {name} ({w}x{d['h']})")
    (OUT / "decor.json").write_text(json.dumps(decor, indent=1))

    # Critters live on the background (they drift with it), so coordinates are in
    # background-image pixels (BG_SIZE). Sprites are stored at their largest size.
    critters = []
    for c in cfg.get("critters", []):
        name = selection.get("critters", {}).get(c["id"], f"{c['id']}_00")
        src = RAW / "critters" / f"{name}.png"
        if not src.exists():
            print(f"skipping {c['id']}: {src.name} not generated")
            continue
        img = remove_bg(src)
        img = img.crop(img.getchannel("A").getbbox())
        h = round(img.height * c["size"] / img.width)
        save_sprite(img.resize((c["size"], h), Image.LANCZOS), OUT / f"critter_{c['id']}.png")
        critters.append({"id": c["id"], "w": c["size"], "h": h, "home": c["home"], "mouth": c["mouth"],
                         "via": c.get("via", c["mouth"]), "walkSpeed": c.get("walk_speed", 12),
                         "depthScale": c.get("depth_scale", 0), "tilt": c.get("tilt", 0), "sandX": c["sand_x"], "sandY": c["sand_y"], "homeScale": c["home_scale"],
                         "bubbles": c.get("bubbles", 0), "bubbleFrom": c.get("bubble_from", c["home"]),
                         "bubbleDarkUntil": c.get("bubble_dark_until"), "bubbleLitBy": c.get("bubble_lit_by")})
        print(f"critter {c['id']} <- {name} ({c['size']}x{h})")
    (OUT / "critters.json").write_text(json.dumps(critters, indent=1))

    bubble_sprite().save(OUT / "bubble.png")
    for i in range(3):
        light_rays(i).save(OUT / f"rays_{i}.png", optimize=True)

    # The splash is a rendered frame of the real scene (with fish), built from the
    # images just written above. Channel icons come from the art/poster.png source.
    import render_preview
    renderer = render_preview.Renderer()
    hero = renderer.render(render_preview.SHOTS["hero"])
    hero.save(OUT / "splash_fhd.jpg", quality=85, optimize=True)
    # Certification 6.4: the splash must also support HD; SD is listed too.
    hero.resize((1280, 720), Image.LANCZOS).save(OUT / "splash_hd.jpg", quality=85, optimize=True)
    cover(hero, (720, 480)).save(OUT / "splash_sd.jpg", quality=85, optimize=True)
    art = render_preview.poster_art(renderer)
    for name, size in (("icon_fhd.jpg", (540, 405)), ("icon_hd.jpg", (290, 218))):
        render_preview.from_art(art, size).save(OUT / name, quality=92)

    total = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"roku/images: {total / 1024:.0f} KB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", action="store_true", help="write contact sheets to tools/raw/sheets")
    args = ap.parse_args()
    if args.sheets:
        contact_sheets()
        return
    sel_path = HERE / "selection.json"
    build(json.loads(sel_path.read_text()) if sel_path.exists() else {})


if __name__ == "__main__":
    main()
