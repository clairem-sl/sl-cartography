#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast

RE_YM = re.compile(r"\d{4}-\d{2}.?")

# Match this with the areas.dir in config.toml
ROOT_DIR = Path(r"C:\Cache\SL-Carto\AreaMaps")


class _Options(Protocol):
    tag: str
    overwrite: bool
    no_jxl: bool
    jxl_q: int
    no_verify_jxl: bool


def _get_options() -> _Options:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true", default=False)
    parser.add_argument("--no-jxl", action="store_true", default=False)
    parser.add_argument("--jxl-q", type=int, default=85)
    parser.add_argument("--no-verify-jxl", action="store_true", default=False)
    parser.add_argument("tag", help="Tag in YYYY-MM format, optionally with one additional character")
    opts = cast(_Options, parser.parse_args())
    if not RE_YM.match(opts.tag):
        print(f"WARNING: tag '{opts.tag}' is not in YYYY-MMx format")
        cont = input("Continue [yN] ? ")
        if cont[0].upper() != "y":
            sys.exit(1)
    return opts


def run_suppressed(args: list[str], quiet: bool = False) -> subprocess.CompletedProcess:  # noqa: D103
    if not quiet:
        print(args[0], end=" ", flush=True)
    return subprocess.run(args=args, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cwebp(src: Path, dst: Path) -> bool:  # noqa: D103
    # cwebp -quiet -preset picture -metadata all "$ff" -o "$targ"
    args: list[str] = f"cwebp -quiet -preset picture -metadata all {src} -o {dst}".split()
    result = run_suppressed(args)
    return result.returncode == 0


def exiftool(src: Path, dst: Path) -> bool:  # noqa: D103
    # exiftool -q -overwrite_original_in_place -tagsFromFile "$ff" -Comment">"UserComment "$targ"
    args: list[str] = f"exiftool -q -overwrite_original_in_place -tagsFromFile {src} -Comment>UserComment {dst}".split()
    result = run_suppressed(args)
    return result.returncode == 0


def cjxl(src: Path, dst: Path, q: int, verify: bool = True) -> bool:  # noqa: D103
    # cjxl.exe .\Bellisseria_ALL.png .\Bellisseria_ALL.2024-04.jxl -q 85
    args: list[str] = f"cjxl {src} {dst} -q {q}".split()
    result = run_suppressed(args)
    if result.returncode == 0 and verify:
        # Extract to stdout (will be suppressed) just to check if decoding is successful
        args = f"djxl {dst} - --output_format ppm".split()
        result = run_suppressed(args)
    return result.returncode == 0


def main(opts: _Options) -> None:  # noqa: D103
    if not ROOT_DIR.exists() or not ROOT_DIR.is_dir():
        print("ERROR: ROOT_DIR not found", file=sys.stderr)
        print("Have you adjusted ROOT_DIR to match config.toml?", file=sys.stderr)
        sys.exit(1)
    tools = ["cwebp", "exiftool"]
    if not opts.no_jxl:
        tools.append("cjxl")
        if not opts.no_verify_jxl:
            tools.append("djxl")
    for cmd in tools:
        if shutil.which(cmd) is None:
            print(f"ERROR: Require '{cmd}' in PATH to run!", file=sys.stderr)
            sys.exit(1)
    for d in sorted(ROOT_DIR.glob("*")):
        if not d.is_dir():
            continue
        print(f"Processing {d}: ", end="", flush=True)
        if not (compositeds := sorted(d.glob("*.composited.png"))):
            print("\n  WARNING: No *.composited.png")
            continue
        if len(compositeds) > 1:
            print("\n  WARNING: More than 1 .composited.png")
            continue
        src = compositeds[0]
        targ_webp = src.with_suffix(f".{opts.tag}.webp")
        targ_jxl = targ_webp.with_suffix(".jxl")
        if targ_webp.exists() or targ_jxl.exists():
            if not opts.overwrite:
                print("Already have an archive and --overwrite not specified")
                continue
            targ_webp.unlink(missing_ok=True)
            targ_jxl.unlink(missing_ok=True)
        if not cwebp(src, targ_webp):
            targ_webp.unlink(missing_ok=True)
            if opts.no_jxl:
                print("\n  ERROR: Failed creating .webp file!")
                continue
            if not cjxl(src, targ_jxl, opts.jxl_q, not opts.no_verify_jxl):
                targ_jxl.unlink(missing_ok=True)
                print("\n  ERROR: Failed creating .webp or .jxl files!")
                continue
            targ = targ_jxl
        else:
            targ = targ_webp
        if not exiftool(src, targ):
            print("\n  ERROR: Failed copying tags!")
            continue
        print("done.")


if __name__ == "__main__":
    main(_get_options())
