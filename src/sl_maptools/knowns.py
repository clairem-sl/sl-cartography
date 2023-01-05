# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from datetime import datetime
from typing import Dict

from sl_maptools import MapBounds, MapCoord

KNOWN_AREAS: Dict[str, MapBounds] = {
    # region ### Linden Continents
    "BellisseriaSouth": MapBounds(1038, 950, 1063, 977),
    "BellisseriaWest": MapBounds(1023, 940, 1045, 977),
    "BellisseriaAtolls": MapBounds(1023, 928, 1032, 940),
    "BellisseriaAnnex": MapBounds(1037, 930, 1053, 949),
    "BellisseriaCentral": MapBounds(1058, 967, 1081, 1000),
    "BellisseriaNorth": MapBounds(1078, 987, 1100, 1024),
    "Zindra": MapBounds(1797, 1179, 1821, 1202),
    "SansaraSnowlands": MapBounds(1003, 979, 1017, 994),
    "Sansara": MapBounds(982, 978, 1038, 1012),
    "Sharp": MapBounds(1159, 988, 1179, 1002),
    "Heterocera": MapBounds(991, 1012, 1014, 1036),
    "Jeogeot": MapBounds(1004, 897, 1039, 939),
    "GaetaV": MapBounds(1159, 1081, 1189, 1099),
    "GaetaI": MapBounds(1140, 1112, 1155, 1130),
    "Satori": MapBounds(1099, 1005, 1134, 1047),
    "Corsica": MapBounds(1100, 1082, 1159, 1100),
    "Nautilus": MapBounds(1106, 1047, 1138, 1081),
    "Horizons": MapBounds(1804, 1200, 1813, 1210),
    "BlakeSea": MapBounds(1131, 1048, 1148, 1054),
    # endregion
    # region ### User Continents
    "SecondNorway": MapBounds(1150, 1041, 1162, 1058),
    "AzureIslands": MapBounds(977, 959, 989, 966),
    "EdenFruitIslands": MapBounds(456, 1700, 481, 1720),
    "Luxory": MapBounds(621, 1033, 632, 1050),
    "Caledon": MapBounds(904, 1020, 909, 1026),
    "PlayaIsles": MapBounds(824, 1207, 831, 1217),
    "Freedom": MapBounds(750, 1013, 758, 1020),
    "TuaruaFiji": MapBounds(1131, 1064, 1149, 1082),
    # endregion
}
VERIFIED_VOIDS: Dict["MapCoord", datetime.date] = {
    # Contains voids that we manually verify using GridSurvey APIs
    # Reason for this CONST is that map sometimes return an image even though there's no actual region/sim at the
    # location.
    # The datetime indicates when the verification is done.

    #
    MapCoord(650, 1265): datetime(2022, 11, 9),
    # This used to be "Spartan Realms". Seems to be abandoned and finally removed.
    MapCoord(1012, 1341): datetime(2022, 11, 9),
}
