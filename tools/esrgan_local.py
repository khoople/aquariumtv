"""Run an ESRGAN-family upscaler file (.pth or .safetensors) directly with spandrel.

WebUI 1.10 only lists .pt/.pth upscalers (and only after a restart), so upscale.py
calls this with the WebUI's own Python, which has torch and spandrel:

  <webui>/venv/Scripts/python.exe esrgan_local.py MODEL IN OUT --scale 2

The image is upscaled by the model's native factor in overlapping tiles, then
resized with Lanczos to the requested scale.
"""
import argparse

import numpy as np
import torch
from PIL import Image
from spandrel import ModelLoader


def upscale(model, img, tile=512, overlap=32):
    s = model.scale
    arr = np.asarray(img, dtype=np.float32) / 255.0
    h, w, _ = arr.shape
    out = np.zeros((h * s, w * s, 3), dtype=np.float32)
    weight = np.zeros((h * s, w * s, 1), dtype=np.float32)
    step = tile - overlap
    ys = list(range(0, max(h - tile, 0) + 1, step))
    xs = list(range(0, max(w - tile, 0) + 1, step))
    if ys[-1] + tile < h:
        ys.append(h - tile)
    if xs[-1] + tile < w:
        xs.append(w - tile)
    ramp = np.minimum(np.arange(tile * s) + 1, overlap * s) / (overlap * s)
    ramp = np.minimum(ramp, ramp[::-1])
    mask = np.outer(ramp, ramp)[..., None].astype(np.float32)
    for y in ys:
        for x in xs:
            t = torch.from_numpy(arr[y:y + tile, x:x + tile].transpose(2, 0, 1).copy())[None].cuda().half()
            with torch.no_grad():
                r = model(t)[0].float().clamp(0, 1).cpu().numpy().transpose(1, 2, 0)
            out[y * s:(y + tile) * s, x * s:(x + tile) * s] += r * mask
            weight[y * s:(y + tile) * s, x * s:(x + tile) * s] += mask
    return Image.fromarray((out / weight * 255.0 + 0.5).clip(0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("src")
    ap.add_argument("dest")
    ap.add_argument("--scale", type=float, default=2.0)
    args = ap.parse_args()

    model = ModelLoader().load_from_file(args.model).eval().cuda().half()
    img = Image.open(args.src).convert("RGB")
    big = upscale(model, img)
    size = (round(img.width * args.scale), round(img.height * args.scale))
    if big.size != size:
        big = big.resize(size, Image.LANCZOS)
    big.save(args.dest)
    print(f"{args.src} {img.size} -> x{model.scale} -> {big.size}")


if __name__ == "__main__":
    main()
