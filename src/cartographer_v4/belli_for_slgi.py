import argparse
from io import StringIO
from pathlib import Path
from typing import cast, NamedTuple

from PIL import Image
from ruamel.yaml import YAML

from sl_maptools import CoordType, AreaBounds, AreaBoundsSet
from sl_maptools.knowns import KNOWN_AREAS
from sl_maptools.validator import inventorize_maps_latest, get_bonnie_coords

BELLI_EXCLUSIONS_YAML = """
AtollsFishermansTown:
    - 1023-1100/940-1023
    - 1034-1100/928-939

Victoria:
    - 1023-1100/928-939
    - 1037-1100/940-946
    - 1040-1100/947-949
    - 1044-1100/950-953
    - 1045-1100/954-957
    - 1044-1100/958-961
    - 1046-1100/962
    - 1047-1100/963-1023
    - 1023-1046/967-1023
    - 1023-1043/966
    - 1023-1042/965
    - 1023-1041/964
    - 1023-1040/963
    - 1023-1039/961-962
    - 1023-1037/960
    - 1023-1038/959
    - 1023-1039/954-958

Fantasseria:
    - 1023-1036/928-1023
    - 1037-1039/946-1023
    - 1040-1100/950-1023
    - 1054-1100/928-949
    - 1037-1100/928-929


"""


class Options(NamedTuple):
    overwrite: bool
    mapdir: Path
    outdir: Path


def get_options() -> Options:
    parser = argparse.ArgumentParser()

    parser.add_argument("--overwrite", action="store_true", default=False)
    parser.add_argument("--mapdir", type=Path, default=Path(r"C:\Cache\SL-Carto\MapTilesMP"))
    parser.add_argument("--outdir", type=Path, default=Path(r"C:\Cache\SL-Carto\AreaMaps\Belli_for_SLGI"))

    _opts = parser.parse_args()

    return cast(Options, _opts)


def main(opts: Options):
    belli_all = KNOWN_AREAS["Bellisseria_ALL"]
    belli_width = belli_all.bounding_box.width * 256
    belli_height = belli_all.bounding_box.height * 256
    belli_coords: set[CoordType] = set(xy for xy in belli_all.xy_iterator())

    bonnie_coords = get_bonnie_coords(None, True)
    map_tiles = inventorize_maps_latest(opts.mapdir)
    
    with StringIO(BELLI_EXCLUSIONS_YAML) as fin:
        data: dict[str, list[str]] = YAML(typ="safe").load(fin)

    print("Creating base ... ", end="", flush=True)
    canvas_base = Image.new("RGBA", (belli_width, belli_height))
    img_tiles: dict[tuple[int, int], Image] = {}
    for xy in belli_coords:
        if xy not in map_tiles or xy not in bonnie_coords:
            continue
        x, y = xy
        canv_x = (x - belli_all.x_westmost) * 256
        canv_y = (belli_all.y_northmost - y) * 256
        with Image.open(map_tiles[x, y]) as img:
            img.load()
            img_tiles[x, y] = img.copy()
            img.putalpha(63)
            canvas_base.paste(img, (canv_x, canv_y))
    del img
    print(f"{len(img_tiles)} tiles", flush=True)

    westmost = belli_all.x_westmost
    nordmost = belli_all.y_northmost
    for mapname, excludes in data.items():
        targ: Path = opts.outdir / f"{mapname}.png"
        if not opts.overwrite and targ.exists():
            print(f"Skipping {mapname}")
            continue
        print(f"Generating {mapname} ... ", end="", flush=True)
        exc = AreaBoundsSet(AreaBounds.from_slgi(e) for e in excludes)
        canvas = canvas_base.copy()

        for xy in belli_coords:
            if xy not in img_tiles:
                continue
            if xy in exc:
                continue
            canv_x = (xy[0] - westmost) * 256
            canv_y = (nordmost - xy[1]) * 256
            canvas.paste(img_tiles[xy], (canv_x, canv_y))

        print(f"saving {targ} ... ", end="", flush=True)
        canvas.save(targ)
        print("done.", flush=True)
        del canvas


if __name__ == "__main__":
    main(get_options())
