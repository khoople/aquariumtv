"""Generate raw aquarium assets through the Stable Diffusion WebUI API.

Requires the WebUI to be running with --api. Writes candidates to tools/raw/,
which process.py then turns into Roku-ready images.

  python generate.py                    # everything that isn't generated yet
  python generate.py background         # just the background
  python generate.py clownfish chromis  # specific fish ids from assets.json
  python generate.py --force -n 6 blue_tang
"""
import argparse
import base64
import json
import random
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"


def txt2img(url, cfg, payload):
    body = {
        "sampler_name": cfg["sampler"],
        "scheduler": cfg["scheduler"],
        "steps": cfg["steps"],
        "cfg_scale": cfg["cfg_scale"],
        "batch_size": 1,
        "n_iter": 1,
        "override_settings": {"sd_model_checkpoint": cfg["model"]},
        "override_settings_restore_afterwards": False,
        **payload,
    }
    r = requests.post(f"{url}/sdapi/v1/txt2img", json=body, timeout=600)
    r.raise_for_status()
    return base64.b64decode(r.json()["images"][0])


def save(path, png, meta):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(f"  wrote {path.relative_to(HERE)}")


def gen_background(url, cfg, n, force, start=0):
    bg = cfg["background"]
    for i in range(start, start + n):
        out = RAW / "background" / f"bg_{i:02d}.png"
        if out.exists() and not force:
            continue
        seed = random.randint(0, 2**31 - 1)
        payload = {
            "prompt": bg["prompt"],
            "negative_prompt": bg["negative"],
            "width": bg["width"],
            "height": bg["height"],
            "seed": seed,
            "enable_hr": True,
            "hr_scale": bg["hr_scale"],
            "hr_upscaler": "Lanczos",
            "denoising_strength": bg["hr_denoise"],
            "hr_second_pass_steps": cfg["steps"],
        }
        print(f"background {i} (seed {seed})")
        save(out, txt2img(url, cfg, payload), {"seed": seed, **payload})


def add_hires(payload, item, cfg):
    """Hires fix (a second pass at higher resolution, for finer detail) when the
    asset asks for it with hr_scale."""
    if item.get("hr_scale"):
        payload.update({
            "enable_hr": True,
            "hr_scale": item["hr_scale"],
            "hr_upscaler": "R-ESRGAN 4x+",
            "denoising_strength": item.get("hr_denoise", 0.4),
            "hr_second_pass_steps": cfg["steps"],
        })


def gen_fish(url, cfg, fish, n, force, start=0):
    common = cfg["fish_common"]
    for i in range(start, start + n):
        out = RAW / "fish" / f"{fish['id']}_{i:02d}.png"
        if out.exists() and not force:
            continue
        seed = random.randint(0, 2**31 - 1)
        payload = {
            "prompt": common["prompt"].format(**fish),
            "negative_prompt": common["negative"],
            "width": fish.get("width", common["width"]),
            "height": fish.get("height", common["height"]),
            "seed": seed,
        }
        add_hires(payload, fish, cfg)
        print(f"{fish['id']} {i} (seed {seed})")
        save(out, txt2img(url, cfg, payload), {"seed": seed, **payload})


def gen_decor(url, cfg, item, n, force, start=0, folder="decor"):
    common = cfg["decor_common"]
    for i in range(start, start + n):
        out = RAW / folder / f"{item['id']}_{i:02d}.png"
        if out.exists() and not force:
            continue
        seed = random.randint(0, 2**31 - 1)
        payload = {
            "prompt": f"{item['prompt']}, {common['suffix']}",
            "negative_prompt": common["negative"],
            "width": item["width"],
            "height": item["height"],
            "seed": seed,
        }
        add_hires(payload, item, cfg)
        print(f"{item['id']} {i} (seed {seed})")
        save(out, txt2img(url, cfg, payload), {"seed": seed, **payload})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", help="'background', fish ids and/or decor ids (default: all)")
    ap.add_argument("-n", "--candidates", type=int, help="candidates per asset (overrides assets.json)")
    ap.add_argument("--force", action="store_true", help="regenerate even if files exist")
    ap.add_argument("--start", type=int, default=0, help="first candidate number (to add to an existing set)")
    ap.add_argument("--url", default="http://127.0.0.1:7860")
    args = ap.parse_args()

    cfg = json.loads((HERE / "assets.json").read_text())
    fish_by_id = {f["id"]: f for f in cfg["fish"]}
    decor_by_id = {d["id"]: d for d in cfg.get("decor", [])}
    critters_by_id = {c["id"]: c for c in cfg.get("critters", [])}
    targets = args.targets or ["background", *fish_by_id, *decor_by_id, *critters_by_id]
    unknown = [t for t in targets if t != "background" and t not in fish_by_id
               and t not in decor_by_id and t not in critters_by_id]
    if unknown:
        sys.exit(f"unknown targets: {', '.join(unknown)}")

    try:
        requests.get(f"{args.url}/sdapi/v1/options", timeout=5).raise_for_status()
    except requests.RequestException as e:
        sys.exit(f"Can't reach the WebUI API at {args.url} ({e}). Launch it with --api.")

    for t in targets:
        if t == "background":
            gen_background(args.url, cfg, args.candidates or cfg["background"]["candidates"], args.force, args.start)
        elif t in critters_by_id:
            # Critters are isolated cutouts like decor, so they share its prompt suffix.
            gen_decor(args.url, cfg, critters_by_id[t], args.candidates or cfg["decor_common"]["candidates"],
                      args.force, args.start, folder="critters")
        elif t in decor_by_id:
            gen_decor(args.url, cfg, decor_by_id[t], args.candidates or cfg["decor_common"]["candidates"], args.force, args.start)
        else:
            gen_fish(args.url, cfg, fish_by_id[t], args.candidates or cfg["fish_common"]["candidates"], args.force, args.start)


if __name__ == "__main__":
    main()
