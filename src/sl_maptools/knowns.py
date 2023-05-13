# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from datetime import datetime
from typing import Final

from sl_maptools import AreaBounds, MapCoord

KNOWN_AREAS: Final[dict[str, AreaBounds]] = {
    # region ### Linden Continents
    "BellisseriaSouth": AreaBounds(1038, 950, 1063, 977),
    "BellisseriaWest": AreaBounds(1023, 940, 1045, 977),
    "BellisseriaAtolls": AreaBounds(1023, 928, 1032, 940),
    "BellisseriaAnnex": AreaBounds(1037, 930, 1053, 949),
    "BellisseriaCentral": AreaBounds(1058, 967, 1081, 1000),
    "BellisseriaNorth": AreaBounds(1078, 987, 1100, 1024),
    "Zindra": AreaBounds(1797, 1179, 1821, 1202),
    "SansaraSnowlands": AreaBounds(1003, 979, 1017, 994),
    "Sansara": AreaBounds(982, 978, 1038, 1012),
    "Sharp": AreaBounds(1159, 988, 1179, 1002),
    "Heterocera": AreaBounds(991, 1012, 1014, 1036),
    "Jeogeot": AreaBounds(1004, 897, 1039, 939),
    "GaetaV": AreaBounds(1159, 1081, 1189, 1099),
    "GaetaI": AreaBounds(1140, 1112, 1155, 1130),
    "Satori": AreaBounds(1099, 1005, 1134, 1047),
    "Corsica": AreaBounds(1100, 1082, 1159, 1100),
    "Nautilus": AreaBounds(1106, 1047, 1138, 1081),
    "Horizons": AreaBounds(1804, 1200, 1813, 1210),
    "BlakeSea": AreaBounds(1131, 1048, 1148, 1054),
    # endregion
    # region ### User Continents
    "SecondNorway": AreaBounds(1150, 1041, 1162, 1058),
    "AzureIslands": AreaBounds(977, 959, 989, 966),
    "EdenFruitIslands": AreaBounds(456, 1700, 481, 1720),
    "Luxory": AreaBounds(621, 1033, 632, 1050),
    "Caledon": AreaBounds(904, 1020, 909, 1026),
    "PlayaIsles": AreaBounds(824, 1207, 831, 1217),
    "Freedom": AreaBounds(750, 1013, 758, 1020),
    "TuaruaFiji": AreaBounds(1131, 1064, 1149, 1082),
    "DragonLands": AreaBounds(859, 984, 865, 989),
    "FantasyLands": AreaBounds(841, 1001, 844, 1010),
    "SouthWestEstates": AreaBounds(686, 920, 692, 928),
    "FarWestEstates": AreaBounds(479, 1271, 485, 1280),
    # endregion
    "LindenEstateServices": AreaBounds(1025, 1014, 1031, 1016),
    "MoleIslands": AreaBounds(1006, 971, 1011, 976),
}

VERIFIED_VOIDS: Final[dict["MapCoord", datetime.date]] = {
    # Contains voids that we manually verify using GridSurvey APIs
    # Reason for this CONST is that map sometimes return an image even though there's no actual region/sim at the
    # location.
    # The datetime indicates when the verification is done.

    #
    MapCoord(650, 1265): datetime(2022, 11, 9),
    # This used to be "Spartan Realms". Seems to be abandoned and finally removed.
    MapCoord(1012, 1341): datetime(2022, 11, 9),
}
