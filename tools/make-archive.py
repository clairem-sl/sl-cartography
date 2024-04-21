#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

try:
    from rich import print as rprint
    from rich.prompt import Prompt
    from rich.traceback import install as rtb_install

    rtb_install(show_locals=True)
except ImportError:
    rprint = None
    Prompt = None
    rtb_install = None


RE_YM = re.compile(r"\d{4}-\d{2}.?")

# Match this with the areas.dir in config.toml
ROOT_DIR = Path(r"C:\Cache\SL-Carto\AreaMaps")

_JXL_DECODERS = ["djxl", "jxl-oxide"]


# noinspection PyCallingNonCallable
def print_(*args, rp: str = "", **kwargs) -> None:  # noqa: ANN002, ANN003
    if rprint:
        if not rp:
            rprint(*args, **kwargs)
        else:
            rprint(f"{rp}{args[0]}", **kwargs)
    else:
        print(*args, **kwargs)


def input_(prompt: str, color: str = "", choices: None | list[str] = None) -> str:
    if Prompt:
        # noinspection PyUnresolvedReferences
        return Prompt.ask(f"{color}{prompt}", choices=choices)
    return input(prompt)


class _Options(Protocol):
    tag: str
    overwrite: bool
    no_jxl: bool
    jxl_q: int
    no_verify_jxl: bool
    jxl_decoder: str


def _get_options() -> _Options:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true", default=False)
    parser.add_argument("--no-jxl", action="store_true", default=False)
    parser.add_argument("--jxl-q", type=int, default=85)
    parser.add_argument("--no-verify-jxl", action="store_true", default=False)
    parser.add_argument("--jxl-decoder", type=str, choices=_JXL_DECODERS, default="djxl")
    parser.add_argument("tag", help="Tag in YYYY-MM format, optionally with one additional character")
    opts = cast(_Options, parser.parse_args())
    if not RE_YM.match(opts.tag):
        print_(f"WARNING: tag '{opts.tag}' is not in YYYY-MMx format", rp="[bold yellow]")
        cont = input_("Continue [yN] ? ", color="[bold white]", choices=["y", "n"])
        if cont[0].upper() != "Y":
            print("Aborted by user.")
            sys.exit(1)
    return opts


def run_suppressed(args: list[str], quiet: bool = False) -> subprocess.CompletedProcess:  # noqa: D103
    if not quiet:
        print_(args[0], rp="[bold cyan]", end=" ", flush=True)
    return subprocess.run(args=args, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cwebp(src: Path, dst: Path) -> bool:  # noqa: D103
    # cwebp -quiet -preset picture -metadata all "$ff" -o "$targ"
    args: list[str] = f"cwebp -quiet -preset picture -metadata all {src} -o {dst}".split()
    result = run_suppressed(args)
    return result.returncode == 0


def exiftool(src: Path, dst: Path, creation_timestamp: datetime) -> bool:  # noqa: D103
    # An example of the command used in shell:
    #
    # exiftool -q -overwrite_original_in_place \
    #   -tagsFromFile SOURCE.composited.png \
    #   -tagsFromFile SOURCE.composited.png \
    #     "-Comment>UserComment" \
    #     "-CreationTime>DateTimeOriginal" \
    #     -TimeZoneOffset=H \
    #     "-OffsetTimeOriginal=+HHMM" \
    #     "-CreateDate=YYYY-mm-dd HH:MM:SS" \
    #     "-OffsetTimeDigitized=+HHMM" \
    #   TARGET.composited.2024-04.webp
    #
    # The "-tagsFromFile" need to be doubled, because the second one *only* copies *exactly* the listed tags after.
    # The first one performs the mass-copying first.
    tz_offset = f"{creation_timestamp:%z}"
    tz_hours = round(creation_timestamp.utcoffset().total_seconds() / 3600.0)
    # Don't forget trailing space for each line of f"", EXCEPT the last one
    args: list[str] = (
        (
            f"exiftool -q -overwrite_original_in_place "
            f"-tagsFromFile {src} "
            f"-tagsFromFile {src} "
            f"-Comment>UserComment "
            f"-CreationTime>DateTimeOriginal "
            f"-TimeZoneOffset={tz_hours} "
            f"-OffsetTimeOriginal={tz_offset}"
        )
        .strip()
        .split()
    )
    # Need to use extend manually because CreateDate has a space in it
    args.extend(
        [
            f"-CreateDate={creation_timestamp:%Y-%m-%d %H:%M:%S}",
            f"-OffsetTimeDigitized={tz_offset}",
            f"{dst}",
        ]
    )
    result = run_suppressed(args)
    return result.returncode == 0


def jxl_verify(target: Path, decoder: str) -> bool:  # noqa: D103
    if decoder == "djxl":
        args = f"djxl {target} - --output_format ppm".split()
    elif decoder == "jxl-oxide":
        args = f"jxl-oxide decode {target}".split()
    else:
        raise NotImplementedError(f"JPEG-XL decoder '{decoder}' is not supported")
    result = run_suppressed(args)
    return result.returncode == 0


def cjxl(src: Path, dst: Path, q: int) -> bool:  # noqa: D103
    # cjxl.exe .\Bellisseria_ALL.png .\Bellisseria_ALL.2024-04.jxl -q 85
    args: list[str] = f"cjxl {src} {dst} -q {q}".split()
    result = run_suppressed(args)
    return result.returncode == 0


def main(opts: _Options) -> None:  # noqa: D103
    if not ROOT_DIR.exists() or not ROOT_DIR.is_dir():
        print_("ERROR: ROOT_DIR not found", file=sys.stderr)
        print_("Have you adjusted ROOT_DIR to match config.toml?", file=sys.stderr)
        sys.exit(1)
    tools = ["cwebp", "exiftool"]
    if not opts.no_jxl:
        tools.append("cjxl")
        if not opts.no_verify_jxl:
            tools.append(opts.jxl_decoder)
    for cmd in tools:
        if shutil.which(cmd) is None:
            print_(f"ERROR: Require '{cmd}' in PATH to run!", file=sys.stderr)
            sys.exit(1)
    for d in sorted(ROOT_DIR.glob("*")):
        if not d.is_dir() or d.name == ".venv":
            continue
        print_(f"{d}: ", end="", flush=True)
        if not (compositeds := sorted(d.glob("*.composited.png"))):
            print_("WARNING: No *.composited.png, skipped", rp="[yellow]")
            continue
        if len(compositeds) > 1:
            print_("WARNING: More than 1 .composited.png, skipped", rp="[yellow]")
            continue
        src = compositeds[0]
        targ_webp = src.with_suffix(f".{opts.tag}.webp")
        targ_jxl = targ_webp.with_suffix(".jxl")
        if targ_webp.exists() or targ_jxl.exists():
            if not opts.overwrite:
                print_("Already have an archive and --overwrite not specified, skipped")
                continue
            targ_webp.unlink(missing_ok=True)
            targ_jxl.unlink(missing_ok=True)
        if not cwebp(src, targ_webp):
            targ_webp.unlink(missing_ok=True)
            if opts.no_jxl:
                print_("  ERROR: Failed creating .webp file!", rp="[bold red]")
                continue
            if _jxl_success := cjxl(src, targ_jxl, opts.jxl_q):
                tstamp = datetime.now().astimezone()
                _jxl_success &= opts.no_verify_jxl or jxl_verify(targ_jxl, opts.jxl_decoder)
            if not _jxl_success:
                targ_jxl.unlink(missing_ok=True)
                print_("  ERROR: Failed creating .webp or .jxl files!", rp="[bold red]")
                continue
            targ = targ_jxl
        else:
            tstamp = datetime.now().astimezone()
            targ = targ_webp
        # noinspection PyUnboundLocalVariable
        if not exiftool(src, targ, tstamp):
            print_("  ERROR: Failed copying tags!", rp="[bold red]")
            continue
        print_("done.")


if __name__ == "__main__":
    main(_get_options())
