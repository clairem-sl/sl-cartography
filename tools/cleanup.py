#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

# Set this to be identical to areas.dir in config.toml
ROOT_DIR = Path(r"C:\Cache\SL-Carto\AreaMaps")

# Set this accordingly if you have dirs in ROOT_DIR that you want to exclude
EXCLUDES = {"_OLD_", "AzureIslands-Old", "K13-Areas", "Belli_for_SLGI"}

SUFFIXES = [
    ".regions.txt",
    ".png",
    ".lattice-overlay.png",
    ".composited.png",
]


def main() -> None:  # noqa: D103
    for d in sorted(ROOT_DIR.glob("*")):
        if not d.is_dir() or d.name in EXCLUDES:
            print(f"Skipping {d}")
            continue
        print(f"Cleaning up {d}")
        for suff in SUFFIXES:
            targ = d / (d.name + suff)
            if not targ.exists():
                print(f"  NotExist: {targ}")
                continue
            targ.unlink()
        print("  Done")


if __name__ == "__main__":
    main()
