"""Render still frames of the screensaver from the built roku/images, for the
channel icons, the splash screen and store screenshots.

It reproduces how AquariumScene draws a frame (layer order, depth tint and
size, far sprites, light rays, background drift and foreground parallax, crab,
bubbles, shark), so the stills show moments that really occur on the TV.
Fish positions are hand-placed per shot in SHOTS.

  python render_preview.py          # writes store/ (poster + screenshots)

The store poster and channel icons come from art/poster.png (see poster_art).
"""
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageOps

HERE = Path(__file__).resolve().parent
IMAGES = HERE.parent / "roku" / "images"
STORE = HERE.parent / "store"
ART = HERE.parent / "art" / "poster.png"
W, H = 1920, 1080

# Mirrors of constants in AquariumScene.xml / .brs.
BG_DRIFT = (-96, -54)
FG_DRIFT = (-170, -60)
RAYS_PIVOT = (992, -540)
RAYS_OFFSET = -90
CRAB_LIT = (0xCB, 0xE4, 0xFF)


def _load(name):
    return Image.open(IMAGES / name).convert("RGBA")


def tint_for(depth):
    """Fish blendColor in swim(): distant fish fade toward the water colour."""
    t = int(140 + 115 * (depth - 0.45) / 0.55)
    return (t, int(t * 0.5 + 127), 255)


def multiply(img, rgb, alpha=1.0):
    out = ImageChops.multiply(img, Image.new("RGBA", img.size, rgb + (255,)))
    if alpha < 1:
        out.putalpha(out.getchannel("A").point(lambda v: int(v * alpha)))
    return out


class Renderer:
    def __init__(self):
        self.species = {s["id"]: s for s in json.loads((IMAGES / "fish.json").read_text())}
        self.decor = json.loads((IMAGES / "decor.json").read_text())
        self.critters = json.loads((IMAGES / "critters.json").read_text())
        self.bg = _load("background.jpg")
        self.rays = [_load(f"rays_{i}.png").resize((2100, 1080), Image.BILINEAR) for i in range(3)]
        self.bubble = _load("bubble.png")
        self.cache = {}

    def sprite(self, name):
        if name not in self.cache:
            self.cache[name] = _load(name)
        return self.cache[name]

    def fish_image(self, fid, face, depth):
        s = self.species[fid]
        far = "_far" if depth < 0.7 and s["kind"] != "shark" else ""
        img = self.sprite(f"fish_{fid}_{face}{far}.png")
        size = (max(1, round(s["w"] * depth)), max(1, round(s["h"] * depth)))
        return multiply(img.resize(size, Image.LANCZOS), tint_for(depth))

    def draw_fish(self, layer, f):
        """f: id, x, y (top-left of the leader, screen px), d (depth), face 'r'/'l',
        optional school (count) and seed for the school formation."""
        s = self.species[f["id"]]
        img = self.fish_image(f["id"], f["face"], f["d"])
        layer.alpha_composite(img, (int(f["x"]), int(f["y"])))
        rng = random.Random(f.get("seed", 1))
        for _ in range(f.get("school", 1) - 1):
            # Followers trail behind the leader, as in swim().
            dx = abs(rng.uniform(-1.6, 1.6) * s["w"]) * (-1 if f["face"] == "r" else 1)
            dy = rng.uniform(-1.2, 1.2) * s["h"]
            layer.alpha_composite(img, (int(f["x"] + dx), int(f["y"] + dy)))

    def draw_bubble(self, layer, x, y, size, alpha, rgb=(255, 255, 255)):
        b = self.bubble.resize((size, size), Image.LANCZOS)
        layer.alpha_composite(multiply(b, rgb, alpha), (int(x - size / 2), int(y - size / 2)))

    def render(self, shot):
        k = shot.get("drift", 0.0)
        bgo = (round(BG_DRIFT[0] * k), round(BG_DRIFT[1] * k))
        fgo = (round(FG_DRIFT[0] * k), round(FG_DRIFT[1] * k))
        rng = random.Random(shot.get("seed", 0))
        frame = Image.new("RGBA", (W, H), (10, 42, 68, 255))

        # Backdrop: background, then critters and their bubbles (drift together).
        backdrop = Image.new("RGBA", self.bg.size, (0, 0, 0, 0))
        backdrop.alpha_composite(self.bg)
        crab = self.critters[0] if self.critters else None
        if crab and shot.get("crab"):
            cx, cy = shot["crab"]
            img = multiply(self.sprite(f"critter_{crab['id']}.png"), CRAB_LIT)
            k = 1 + (cy - crab["sandY"][0]) * crab.get("depthScale", 0)
            if k != 1:
                img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
            if crab.get("tilt"):
                img = img.rotate(math.degrees(crab["tilt"]), resample=Image.BICUBIC)
            backdrop.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height)))
        elif crab and shot.get("cave_bubbles", True):
            # Only while the crab is hidden: dim in the cave, bright once clear of it.
            ex, ey = crab["bubbleFrom"]
            for i in range(crab["bubbles"]):
                y = ey - rng.uniform(0.1, 0.9) * (ey + 80)
                lit = np.interp(y, [crab["bubbleLitBy"], crab["bubbleDarkUntil"]], [1, 0])
                rgb = tuple(int(v) for v in np.array((0x3A, 0x46, 0x58)) * (1 - lit) + 255 * lit)
                self.draw_bubble(backdrop, ex + rng.uniform(-30, 30), y, rng.randint(10, 24),
                                 rng.uniform(.5, .9) * (0.35 + 0.65 * lit), rgb)
        frame.alpha_composite(backdrop, bgo)

        fish = shot.get("fish", [])
        layers = {"far": [f for f in fish if f["d"] < 0.65],
                  "mid": [f for f in fish if 0.65 <= f["d"] < 0.85],
                  "near": [f for f in fish if f["d"] >= 0.85]}
        for f in layers["far"]:
            self.draw_fish(frame, f)

        # Light rays: three layers at their current shimmer, rotated about the sun.
        rays = Image.new("RGBA", (2100, 1080 + 400), (0, 0, 0, 0))
        for img, a in zip(self.rays, shot.get("rays", (0.8, 0.6, 0.7))):
            rays.alpha_composite(multiply(img, (255, 255, 255), a), (0, 400))
        rays = rays.rotate(math.degrees(shot.get("ray_rot", 0.0)), resample=Image.BILINEAR,
                           center=(RAYS_PIVOT[0], RAYS_PIVOT[1] + 400))
        frame.alpha_composite(rays.crop((0, 400, 2100, 1480)), (RAYS_OFFSET, 0))

        for f in layers["mid"]:
            self.draw_fish(frame, f)
        for f in layers["near"]:
            self.draw_fish(frame, f)
        if shot.get("shark"):
            self.draw_fish(frame, dict(shot["shark"], id="reef_shark"))

        # Foreground decor (with its bubbles just behind it), shifted by parallax.
        fg = Image.new("RGBA", (W + 400, H + 200), (0, 0, 0, 0))
        for d in self.decor:
            if d["bubbles"]:
                ex, ey = d["x"] + d["w"] / 2, d["y"] + d["h"] * 0.6
                for _ in range(d["bubbles"]):
                    self.draw_bubble(fg, ex + rng.uniform(-d["w"] * .15, d["w"] * .15) + rng.uniform(-14, 14),
                                     ey - rng.random() ** 2 * (ey + 80), rng.randint(8, 26), rng.uniform(.5, .9))
            fg.alpha_composite(self.sprite(f"fg_{d['id']}.png"), (d["x"], d["y"]))
        frame.alpha_composite(fg, fgo)
        return frame.convert("RGB")


# Each shot is a moment the screensaver can actually show. Shark shots keep the
# tank sparse, since fish stop entering 30 s before it arrives.
SHOTS = {
    "hero": dict(drift=0.25, seed=3, rays=(0.9, 0.55, 0.8), ray_rot=-0.005, fish=[
        dict(id="emperor_angel", x=720, y=330, d=1.0, face="r"),
        dict(id="blue_tang", x=1130, y=470, d=0.95, face="l"),
        dict(id="clownfish", x=560, y=600, d=0.9, face="r"),
        dict(id="yellow_tang", x=1240, y=250, d=0.8, face="l"),
        dict(id="moorish_idol", x=380, y=240, d=0.7, face="r"),
        dict(id="flame_angel", x=1000, y=690, d=0.75, face="l"),
        dict(id="chromis", x=1360, y=120, d=0.55, face="l", school=6, seed=4),
        dict(id="royal_gramma", x=260, y=520, d=0.6, face="r"),
        dict(id="butterflyfish", x=1460, y=440, d=0.6, face="l"),
    ]),
    "reef": dict(drift=0.6, seed=8, rays=(0.6, 0.9, 0.5), ray_rot=0.006, fish=[
        dict(id="lionfish", x=1020, y=330, d=0.95, face="l"),
        dict(id="moorish_idol", x=420, y=420, d=0.9, face="r"),
        dict(id="mandarin", x=760, y=760, d=0.85, face="r"),
        dict(id="clownfish", x=1380, y=640, d=0.8, face="l"),
        dict(id="chromis", x=640, y=180, d=0.7, face="r", school=7, seed=2),
        dict(id="yellow_tang", x=180, y=280, d=0.6, face="r"),
        dict(id="blue_tang", x=1500, y=220, d=0.55, face="l"),
        dict(id="flame_angel", x=1240, y=520, d=0.5, face="r"),
        dict(id="royal_gramma", x=930, y=560, d=0.5, face="l"),
    ]),
    "crab": dict(drift=0.45, seed=5, crab=(985, 1040), rays=(0.7, 0.7, 0.9), ray_rot=0, fish=[
        dict(id="flame_angel", x=500, y=460, d=0.95, face="r"),
        dict(id="butterflyfish", x=1260, y=380, d=0.85, face="l"),
        dict(id="emperor_angel", x=820, y=230, d=0.7, face="l"),
        dict(id="clownfish", x=1520, y=600, d=0.65, face="l"),
        dict(id="chromis", x=300, y=200, d=0.55, face="r", school=5, seed=9),
        dict(id="royal_gramma", x=1100, y=640, d=0.5, face="r"),
    ]),
    "shark": dict(drift=0.8, seed=6, rays=(0.85, 0.5, 0.75), ray_rot=-0.0075,
                  shark=dict(x=520, y=250, d=0.95, face="r"), fish=[
        dict(id="yellow_tang", x=1520, y=660, d=0.55, face="r"),
        dict(id="chromis", x=180, y=720, d=0.5, face="l", school=5, seed=7),
        dict(id="moorish_idol", x=1250, y=150, d=0.5, face="r"),
    ]),
    "school": dict(drift=0.05, seed=12, rays=(1.0, 0.45, 0.6), ray_rot=0.009, fish=[
        dict(id="chromis", x=980, y=300, d=0.95, face="r", school=7, seed=21),
        dict(id="chromis", x=640, y=560, d=0.75, face="l", school=6, seed=5),
        dict(id="emperor_angel", x=260, y=330, d=0.85, face="r"),
        dict(id="lionfish", x=1380, y=520, d=0.7, face="l"),
        dict(id="mandarin", x=1180, y=780, d=0.6, face="r"),
        dict(id="blue_tang", x=420, y=180, d=0.55, face="l"),
    ]),
}

SCREENSHOTS = ["hero", "reef", "crab", "shark", "school"]


def poster_art(renderer=None):
    """The 4:3 source for the store poster and channel icons: art/poster.png.

    Edit that file to change them (add a title, etc.); it is never overwritten.
    If it doesn't exist yet it is seeded with a text-free render of the hero
    shot. Non-4:3 art is centre-cropped and transparency is flattened onto the
    tank colour, since Roku artwork must be opaque."""
    if not ART.exists():
        ART.parent.mkdir(exist_ok=True)
        hero = (renderer or Renderer()).render(SHOTS["hero"])
        # A 4:3 crop around the hero fish, so they stay large at icon size.
        hero.crop((240, 0, 1680, 1080)).save(ART)
        print(f"seeded {ART.relative_to(HERE.parent)} (1440x1080); edit it to change the poster and icons")
    img = Image.open(ART)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGBA", img.size, (0x0A, 0x2A, 0x44, 255))
        flat.alpha_composite(img)
        img = flat
    img = img.convert("RGB")
    if abs(img.width / img.height - 4 / 3) > 0.01:
        print(f"note: {ART.name} is {img.width}x{img.height}, not 4:3; centre-cropping")
    if img.width < 540:
        print(f"note: {ART.name} is narrower than 540 px; the poster will be upscaled")
    return img


def from_art(art, size):
    return ImageOps.fit(art, size, Image.LANCZOS)


def main():
    r = Renderer()
    STORE.mkdir(exist_ok=True)
    from_art(poster_art(r), (540, 405)).save(STORE / "poster_540x405.png")
    for i, name in enumerate(SCREENSHOTS, 1):
        r.render(SHOTS[name]).save(STORE / f"screenshot_{i}_{name}.jpg", quality=92)
    print(f"wrote store/: poster_540x405.png and {len(SCREENSHOTS)} screenshots")


if __name__ == "__main__":
    main()
