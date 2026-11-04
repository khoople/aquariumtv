"""Upscale a raw background with an ESRGAN pass plus a tiled SD img2img detail pass.

  python upscale.py bg_01            # -> raw/background/bg_01_4k.png (original untouched)
  python upscale.py bg_01 --denoise 0.25 --scale 2

The img2img pass re-renders overlapping tiles at low denoise so SD adds texture
the ESRGAN pass can't invent; tiles are feather-blended to hide seams.
"""
import argparse
import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import requests
from PIL import Image

HERE = Path(__file__).resolve().parent
BG = HERE / "raw" / "background"

PROMPT = ("underwater photograph of a saltwater coral reef, intricate coral texture, sea anemones, "
          "white sand, deep blue water, sunlight caustics, sharp focus, highly detailed, 8k")
NEGATIVE = "fish, text, watermark, blurry, lowres, jpeg artifacts, painting, cartoon"


def b64(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def unb64(s):
    return Image.open(io.BytesIO(base64.b64decode(s))).convert("RGB")


def esrgan(url, img, scale, upscaler):
    r = requests.post(f"{url}/sdapi/v1/extra-single-image", timeout=600, json={
        "image": b64(img), "upscaling_resize": scale, "upscaler_1": upscaler})
    r.raise_for_status()
    return unb64(r.json()["image"])


def positions(length, tile, overlap):
    step = tile - overlap
    pos = list(range(0, max(length - tile, 0) + 1, step))
    if pos[-1] + tile < length:
        pos.append(length - tile)
    return pos


def feather(tile, overlap):
    ramp = np.minimum(np.arange(tile) + 1, overlap) / overlap
    ramp = np.minimum(ramp, ramp[::-1])
    return np.outer(ramp, ramp)[..., None]


def detail_pass(url, cfg, img, args):
    w, h = img.size
    t, ov = args.tile, args.overlap
    acc = np.zeros((h, w, 3))
    weight = np.zeros((h, w, 1))
    mask = feather(t, ov)
    xs, ys = positions(w, t, ov), positions(h, t, ov)
    n = 0
    for y in ys:
        for x in xs:
            n += 1
            print(f"  tile {n}/{len(xs) * len(ys)} at {x},{y}")
            r = requests.post(f"{url}/sdapi/v1/img2img", timeout=600, json={
                "init_images": [b64(img.crop((x, y, x + t, y + t)))],
                "prompt": PROMPT, "negative_prompt": NEGATIVE,
                "denoising_strength": args.denoise,
                "width": t, "height": t, "seed": args.seed,
                "sampler_name": args.sampler or cfg["sampler"], "scheduler": cfg["scheduler"],
                "steps": args.steps, "cfg_scale": args.cfg or cfg["cfg_scale"],
                "override_settings": {"sd_model_checkpoint": args.model or cfg["model"], "upcast_attn": args.upcast},
            })
            r.raise_for_status()
            out = np.asarray(unb64(r.json()["images"][0]), dtype=np.float64)
            acc[y:y + t, x:x + t] += out * mask
            weight[y:y + t, x:x + t] += mask
    return Image.fromarray(np.clip(acc / weight, 0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="raw background name, e.g. bg_01")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--upscaler", default="R-ESRGAN 4x+")
    ap.add_argument("--denoise", type=float, default=0.3)
    ap.add_argument("--steps", type=int, default=12, help="scaled by denoise, so ~steps*denoise actually run")
    ap.add_argument("--tile", type=int, default=1024)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--model", help="checkpoint for the detail pass (default: assets.json model)")
    ap.add_argument("--sampler")
    ap.add_argument("--upcast", action="store_true", help="upcast attention to fp32 (fixes NaNs with some checkpoints)")
    ap.add_argument("--cfg", type=float)
    ap.add_argument("--out", help="output name (default: <name>_4k)")
    ap.add_argument("--url", default="http://127.0.0.1:7860")
    args = ap.parse_args()

    src = BG / f"{args.name}.png"
    if not src.exists():
        sys.exit(f"{src} not found")
    cfg = json.loads((HERE / "assets.json").read_text())

    img = Image.open(src).convert("RGB")
    print(f"{src.name} {img.size} -> {args.upscaler} x{args.scale}")
    esr = BG / f"{args.name}_esrgan.png"
    if esr.exists() and Image.open(esr).size == (round(img.width * args.scale), round(img.height * args.scale)):
        big = Image.open(esr).convert("RGB")
    else:
        big = esrgan(args.url, img, args.scale, args.upscaler)
        big.save(esr)
    print(f"detail pass on {big.size}")
    out = detail_pass(args.url, cfg, big, args)
    dest = BG / f"{args.out or args.name + '_4k'}.png"
    out.save(dest)
    print(f"wrote {dest.relative_to(HERE)} {out.size}")


if __name__ == "__main__":
    main()
