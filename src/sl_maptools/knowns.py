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
    "SeabirdIslands": AreaBounds(686, 920, 692, 928),
    "TropicalCoralIslands": AreaBounds(479, 1271, 485, 1280),
    "Gooseberry-Briarwood": AreaBounds(666, 1423, 674, 1429),
    "TrinidadTobago": AreaBounds(x_westmost=902, y_southmost=1372, x_eastmost=906, y_northmost=1376),
    "NativeIslands": AreaBounds(x_westmost=733, y_southmost=1367, x_eastmost=738, y_northmost=1371),
    "MauiIslandEstates": AreaBounds(x_westmost=548, y_southmost=1137, x_eastmost=551, y_northmost=1140),
    "Rosehaven": AreaBounds(x_westmost=906, y_southmost=1029, x_eastmost=909, y_northmost=1034),
    "TortugaIslands": AreaBounds(x_westmost=500, y_southmost=1010, x_eastmost=504, y_northmost=1013),
    "SeductionEstate": AreaBounds(x_westmost=757, y_southmost=926, x_eastmost=763, y_northmost=932),
    "AntiquityLand": AreaBounds(x_westmost=763, y_southmost=909, x_eastmost=766, y_northmost=913),
    "NewHaven": AreaBounds(x_westmost=597, y_southmost=1181, x_eastmost=603, y_northmost=1184),
    "TheGroveEstate": AreaBounds(x_westmost=1000, y_southmost=1166, x_eastmost=1008, y_northmost=1171),
    "GoreanLands": AreaBounds(x_westmost=1014, y_southmost=1175, x_eastmost=1020, y_northmost=1179),
    # endregion
    # region ### Premium Continents
    "EastPremium": AreaBounds(x_westmost=1192, y_southmost=907, x_eastmost=1215, y_northmost=926),
    "SouthPremium-North": AreaBounds(x_westmost=1013, y_southmost=811, x_eastmost=1028, y_northmost=828),
    "SouthPremium-Middle": AreaBounds(x_westmost=1000, y_southmost=750, x_eastmost=1022, y_northmost=768),
    "SouthPremium-South": AreaBounds(x_westmost=1000, y_southmost=500, x_eastmost=1022, y_northmost=518),
    # endregion
    # region ### Special Regions
    "LindenEstateServices": AreaBounds(1025, 1014, 1031, 1016),
    "MoleIslands": AreaBounds(1006, 971, 1011, 976),
    "SLBRegions": AreaBounds(x_westmost=390, y_southmost=367, x_eastmost=395, y_northmost=372),
    "SSP-15xx": AreaBounds(x_westmost=1155, y_southmost=1379, x_eastmost=1165, y_northmost=1383),
    "SSP-40xx": AreaBounds(x_westmost=1182, y_southmost=1371, x_eastmost=1187, y_northmost=1377),
    # endregion
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
