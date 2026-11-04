"""Zip roku/ into dist/aquariumtv.zip and optionally sideload it.

  python package.py                 # bump build_version, then build the zip
  python package.py --deploy        # same, then install; needs ROKU_IP and ROKU_PASS env vars
  python package.py --debug         # dist/aquariumtv_debug.zip with the debug overlay on

Every release build increments build_version in roku/manifest, because Roku only
accepts an update whose version is higher than the published one. Debug builds
are diagnostics that never go to the store, so they leave it alone.
"""
import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

import requests
from requests.auth import HTTPDigestAuth

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "roku"


def bump_build_version():
    manifest = SRC / "manifest"
    text = manifest.read_bytes().decode()          # bytes keep the file's line endings
    match = re.search(r"^build_version=(\d+)\s*$", text, re.M)
    if not match:
        sys.exit("roku/manifest has no numeric build_version line")
    old = int(match.group(1))
    text = text[:match.start(1)] + str(old + 1) + text[match.end(1):]
    manifest.write_bytes(text.encode())
    major = re.search(r"^major_version=(\d+)", text, re.M).group(1)
    minor = re.search(r"^minor_version=(\d+)", text, re.M).group(1)
    print(f"version {major}.{minor}.{old} -> {major}.{minor}.{old + 1}")


def build(debug=False):
    dist = ROOT / "dist" / ("aquariumtv_debug.zip" if debug else "aquariumtv.zip")
    dist.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(dist, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(SRC.rglob("*")):
            if not p.is_file():
                continue
            name = p.relative_to(SRC).as_posix()
            if name == "manifest" and debug:
                # Flip the compile-time flag only inside the debug zip; the
                # manifest on disk (and the release zip) keep it off.
                text = p.read_text()
                assert "DEBUG_OVERLAY=false" in text, "manifest has no DEBUG_OVERLAY bs_const"
                z.writestr(name, text.replace("DEBUG_OVERLAY=false", "DEBUG_OVERLAY=true"))
            else:
                z.write(p, name)
    print(f"{dist.relative_to(ROOT)}: {dist.stat().st_size / 1024:.0f} KB")
    return dist


def deploy(dist):
    ip, pw = os.environ.get("ROKU_IP"), os.environ.get("ROKU_PASS")
    if not ip or not pw:
        sys.exit("set ROKU_IP and ROKU_PASS (the developer-mode password) to deploy")
    with dist.open("rb") as f:
        r = requests.post(f"http://{ip}/plugin_install", auth=HTTPDigestAuth("rokudev", pw),
                          files={"archive": (dist.name, f, "application/zip")},
                          data={"mysubmit": "Install"}, timeout=60)
    r.raise_for_status()
    ok = "Install Success" in r.text or "Identical to previous version" in r.text
    print("installed" if ok else "install response didn't report success; check the device")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--debug", action="store_true", help="build the diagnostic overlay build instead")
    args = ap.parse_args()
    if not args.debug:
        bump_build_version()
    dist = build(args.debug)
    if args.deploy:
        deploy(dist)
