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
    "TrinidadTobago": AreaBounds(902, 1372, 906, 1376),
    "NativeIslands": AreaBounds(733, 1367, 738, 1371),
    "MauiIslandEstates": AreaBounds(548, 1137, 551, 1140),
    "Rosehaven": AreaBounds(906, 1029, 909, 1034),
    "TortugaIslands": AreaBounds(500, 1010, 504, 1013),
    "SeductionEstate": AreaBounds(757, 926, 763, 932),
    "AntiquityLand": AreaBounds(763, 909, 766, 913),
    "NewHaven": AreaBounds(597, 1181, 603, 1184),
    "TheGroveEstate": AreaBounds(1000, 1166, 1008, 1171),
    "TheWastelands": AreaBounds(785, 1036, 787, 1039),
    "CedarCreek": AreaBounds(849, 1342, 853, 1346),
    "PlumIslandSoundEstate": AreaBounds(921, 1168, 923, 1171),
    "AMEstate": AreaBounds(606, 1164, 608, 1167),
    "CalasGaladhonPark": AreaBounds(709, 1110, 713, 1113),
    "IsleOfWyrms": AreaBounds(545, 1059, 548, 1063),
    "AmazonRiver": AreaBounds(832, 969, 835, 972),
    "Baunatal": AreaBounds(715, 922, 718, 924),
    # endregion
    # region ### User Continents - Tentative
    "GoreanLands": AreaBounds(1014, 1175, 1020, 1179),
    "AngelManor": AreaBounds(1054, 1397, 1056, 1400),
    "NakedEstates": AreaBounds(1038, 1161, 1042, 1163),
    "Western": AreaBounds(963, 1145, 967, 1149),
    "Babbage": AreaBounds(630, 1004, 633, 1007),
    "Capitol": AreaBounds(641, 995, 645, 998),
    "SunIslands": AreaBounds(876, 987, 878, 990),
    "Mieville": AreaBounds(533, 1196, 537, 1201),
    "Pirates1700": AreaBounds(940, 1174, 942, 1177),
    "Mythera": AreaBounds(720, 1324, 722, 1328),
    "SecondFrance": AreaBounds(556, 1117, 559, 1120),
    # endregion
    # region ### Premium Continents
    "EastPremium": AreaBounds(1192, 907, 1215, 926),
    "SouthPremium-North": AreaBounds(1013, 811, 1028, 828),
    "SouthPremium-Middle": AreaBounds(1000, 750, 1022, 768),
    "SouthPremium-South": AreaBounds(1000, 500, 1022, 518),
    # endregion
    # region ### Special Areas
    "LindenLabDE": AreaBounds(1105, 1382, 1108, 1388),
    "LindenEstateServices": AreaBounds(1025, 1014, 1031, 1016),
    "MoleIslands": AreaBounds(1006, 971, 1011, 976),
    "SLBRegions": AreaBounds(390, 367, 395, 372),
    "SSP-15xx": AreaBounds(1155, 1379, 1165, 1383),
    "SSP-40xx": AreaBounds(1182, 1371, 1187, 1377),
    "LR-160": AreaBounds(1187, 1206, 1190, 1210),
    "LR-180": AreaBounds(1193, 1206, 1196, 1210),
    "Preflight": AreaBounds(1296, 1193, 1299, 1196),
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
