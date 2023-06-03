
from itertools import combinations

from sl_maptools import AreaBounds
from sl_maptools.knowns import KNOWN_AREAS


def main():
    areas = [(name, bounds) for name, bounds in KNOWN_AREAS.items()]
    na1: tuple[str, AreaBounds]
    na2: tuple[str, AreaBounds]
    for na1, na2 in combinations(areas, 2):
        n1, a1 = na1
        n2, a2 = na2
        if (inter := a1.intersection(a2)) is not None:
            print(f"{n1} ∩ {n2} = {inter!r}")


if __name__ == '__main__':
    main()
