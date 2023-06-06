# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

from typing import Final, Generator, Union

from sl_maptools import AreaBounds, AreaDescriptor

# fmt: off
KNOWN_AREAS: Final[dict[str, Union[AreaBounds, AreaDescriptor]]] = {
    # region ### Linden Continents - Bellisseria

    # region ## Original, self-made segmentation of Bellisseria area
    "Bellisseria_CM_South": AreaBounds(1038, 950, 1063, 977),
    "Bellisseria_CM_West": AreaBounds(1023, 940, 1045, 977),
    "Bellisseria_CM_Atolls": AreaBounds(1023, 928, 1032, 940),
    "Bellisseria_CM_Annex": AreaBounds(1037, 930, 1053, 949),
    "Bellisseria_CM_Central": AreaBounds(1058, 967, 1081, 1000),
    "Bellisseria_CM_North": AreaBounds(1078, 987, 1100, 1024),
    # endregion

    # region ## SLGI-assigned names / segmentation of the Belli. area
    "Bellisseria_SLGI_Forest": AreaBounds(1043, 950, 1063, 977),
    "Bellisseria_SLGI_Victorian": AreaBounds(1024, 941, 1046, 966),
    "Bellisseria_SLGI_Jeogeot": AreaBounds(1023, 928, 1035, 943),
    "Bellisseria_SLGI_East": AreaBounds(1078, 987, 1100, 1024),
    "Bellisseria_SLGI_Magic": AreaBounds(1037, 930, 1053, 949),
    "Bellisseria_SLGI_Primordial": AreaBounds(1023, 953, 1045, 977),
    "Bellisseria_SLGI_Sakura": AreaBounds(1063, 992, 1072, 1000),
    "Bellisseria_SLGI_WaterParadise": AreaBounds(1058, 967, 1081, 992),
    # endregion

    # endregion

    # region ### Linden Continents - Non Bellisseria
    "Zindra": AreaBounds(1797, 1179, 1821, 1202),
    "SansaraSnowlands": AreaBounds(1003, 979, 1018, 995),
    "Sansara": AreaBounds(982, 978, 1038, 1012),
    "SeaOfFables": AreaBounds(1015, 992, 1023, 999),
    "BayCityPlains": AreaBounds(982, 999, 995, 1006),
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

    # region ### Premium Continents
    "EastPremium": AreaBounds(1192, 907, 1215, 926),
    "SouthPremium-North": AreaBounds(1013, 811, 1028, 828),
    "SouthPremium-Middle": AreaBounds(1000, 750, 1022, 768),
    "SouthPremium-South": AreaBounds(1000, 500, 1022, 518),
    # endregion

    # region ### User Continents
    "BlakeSeaSurrounding": AreaBounds(1131, 1036, 1152, 1061),
    "BlakeSeaSurroundingNoSuppress": AreaBounds(1131, 1036, 1152, 1061),
    "SecondNorway": AreaBounds(1149, 1041, 1165, 1063),
    "AzureIslands": AreaBounds(977, 959, 989, 966),
    "EdenFruitIslands": AreaBounds(459, 1700, 481, 1720),
    "Luxory": AreaBounds(621, 1033, 632, 1050),
    "Caledon": AreaBounds(905, 1020, 909, 1025),
    "PlayaIsles": AreaBounds(824, 1207, 831, 1217),
    "Freedom": AreaBounds(750, 1013, 758, 1020),
    "TuaruaFiji": AreaBounds(1131, 1064, 1149, 1082),
    "Uhre": AreaBounds(860, 984, 865, 989),
    "FantasyLands": AreaBounds(841, 1001, 844, 1010),
    "SeabirdIslands": AreaBounds(686, 920, 692, 928),
    "CoralOcean": AreaBounds(479, 1271, 485, 1280),
    "Gooseberry": AreaBounds(669, 1423, 674, 1429),
    # "TrinidadTobago": AreaBounds(902, 1372, 906, 1376),
    "AllenCommunity": AreaBounds.from_slgi("902-906/1372-1376"),
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
    "AMEstate": AreaBounds(604, 1164, 609, 1169),
    "CalasGaladhonPark": AreaBounds(709, 1110, 713, 1113),
    "IsleOfWyrms": AreaBounds(545, 1059, 548, 1063),
    "AmazonRiver": AreaBounds(832, 969, 835, 972),
    "Baunatal": AreaBounds(715, 922, 718, 924),
    "CrackDen": AreaBounds(742, 1389, 745, 1391),
    "MadisonCounty": AreaBounds(850, 1320, 852, 1323),
    "TempletonCove": AreaBounds(1027, 1240, 1030, 1242),
    "Mythera": AreaBounds(720, 1324, 722, 1328),
    "JunglesOfGor": AreaBounds(1097, 949, 1099, 951),
    "Raglan": AreaBounds(1083, 1296, 1086, 1299),
    "FairChang": AreaBounds(1103, 1048, 1110, 1060),
    "MeisterbastlerKreis": AreaBounds.from_slgi("1105-1114/1382-1388"),
    # endregion
    # region ### User Continents - Tentative
    "GoreanLands": AreaBounds(1014, 1175, 1020, 1179),
    "AngelManor": AreaBounds(1054, 1397, 1056, 1400),
    "NakedEstates": AreaBounds(1038, 1161, 1042, 1163),
    "WildWest": AreaBounds(963, 1145, 967, 1149),
    "Babbage": AreaBounds(630, 1004, 633, 1007),
    "Capitol": AreaBounds(641, 995, 645, 998),
    "SunIslands": AreaBounds(876, 987, 878, 990),
    "Mieville": AreaBounds(533, 1196, 537, 1202),
    "Pirates1700": AreaBounds(940, 1174, 942, 1177),
    "Coeur": AreaBounds(554, 1117, 559, 1124),
    "SnugHarbor": AreaBounds(1146, 1052, 1149, 1056),
    "ASLMetaverse": AreaBounds(763, 915, 765, 917),
    # ### Below this line, are areas with < 10 regions in a clump
    "Yumix": AreaBounds(653, 1245, 654, 1249),
    "VWBPE": AreaBounds(1102, 1312, 1106, 1314),
    "Maple": AreaBounds(878, 927, 882, 928),
    "BlackBay": AreaBounds(615, 1058, 617, 1060),
    "Schindleria": AreaBounds(527, 1027, 529, 1029),
    "MayaLake": AreaBounds(979, 1198, 981, 1200),
    "MacedoniaEstate": AreaBounds(540, 1182, 544, 1185),
    "Bauer": AreaBounds(899, 1200, 902, 1202),
    "Olni": AreaBounds(655, 1291, 658, 1293),
    "Romanum": AreaBounds(747, 1079, 749, 1083),
    "EndOfTime": AreaBounds(500, 1027, 503, 1030),
    # endregion
    # region ### Special Areas
    "LindenEstateServices": AreaBounds(1025, 1014, 1031, 1016),
    "MoleIslands": AreaBounds(1006, 971, 1011, 976),
    # "SLBRegions": AreaBounds(390, 359, 402, 374),
    "LR-160": AreaBounds(1187, 1206, 1190, 1210),
    "LR-180": AreaBounds(1193, 1206, 1196, 1210),
    "Preflight": AreaBounds(1296, 1193, 1299, 1196),
    # "TheMists": AreaBounds(562, 734, 567, 739),  ### Former site of Fantasy Faire 2023
    # TheMists disappeared in June 2023
    "PaleoQuest": AreaBounds(400, 392, 401, 400),
    # "RFL2023": AreaBounds(503, 705, 554, 1621),
    "RFL2023": AreaBounds(547, 705, 554, 716),
    # "SLB2023": AreaBounds(386, 368, 403, 377),
    "SLB2023": AreaBounds(386, 359, 403, 377),
    # endregion
}

_SUPPRESS_FOR_AREAS: Final[dict[str, list[AreaBounds]]] = {
    "FairChang": [
        AreaBounds(1106, 1057, 1110, 1061),
        AreaBounds(1109, 1055, 1110, 1056),
        AreaBounds(1110, 1052, 1110, 1054),
    ],
    "SnugHarbor": [AreaBounds(1146, 1056, 1146, 1056)],
    "BlakeSeaSurrounding": [
        AreaBounds(1149, 1055, 1152, 1061),  # Second Norway
        AreaBounds(1150, 1049, 1152, 1054),  # Second Norway
        AreaBounds(1131, 1039, 1134, 1046),  # Satori
        AreaBounds(1133, 1047, 1134, 1047),  # Satori
        AreaBounds(1131, 1048, 1131, 1061),  # Nautilus / Citadel
        AreaBounds(1132, 1052, 1132, 1061),  # Nautilus
        AreaBounds(1133, 1055, 1134, 1061),  # Nautilus
        AreaBounds(1134, 1054, 1134, 1054),  # Nautilus
    ],
    "Bellisseria_SLGI_Forest": [
        AreaBounds(1063, 977, 1063, 977),  # Part of Belliseria Water Paradise
        AreaBounds(1038, 964, 1045, 977),  # Part of Belliseria Primordial / Victorian
        AreaBounds(1038, 963, 1044, 963),  # Part of Belliseria Primordial / Victorian
        AreaBounds(1038, 950, 1042, 962),  # Part of Belliseria Primordial / Victorian
        AreaBounds(1043, 955, 1043, 956),  # Part of Belliseria Primordial / Victorian
    ],
    "Bellisseria_SLGI_Victorian": [
        AreaBounds(1024, 966, 1043, 966),
        AreaBounds(1024, 965, 1042, 965),
        AreaBounds(1024, 964, 1041, 964),
        AreaBounds(1024, 959, 1040, 963),
        AreaBounds(1024, 954, 1039, 958),
        AreaBounds(1046, 941, 1046, 962),
        AreaBounds(1045, 941, 1045, 961),
        AreaBounds(1044, 958, 1044, 961),
        AreaBounds(1044, 941, 1044, 953),
        AreaBounds(1040, 941, 1043, 948),
        AreaBounds(1037, 941, 1039, 945),
        AreaBounds(1035, 941, 1039, 943),
        AreaBounds(1024, 941, 1024, 941),
    ],
    "Bellisseria_SLGI_Jeogeot": [
        AreaBounds(1023, 942, 1034, 943),
        AreaBounds(1025, 941, 1034, 941),
        AreaBounds(1031, 935, 1035, 939),
        AreaBounds(1029, 935, 1030, 937),
        AreaBounds(1031, 935, 1035, 939),
        AreaBounds(1032, 928, 1035, 934),
        AreaBounds(1029, 928, 1031, 931),
        AreaBounds.from_slgi("1028/928-929"),
        AreaBounds.from_slgi("1026-1027/928"),
    ],
    "Bellisseria_SLGI_East": [
        AreaBounds.from_slgi("1100/1005-1010"),
        AreaBounds(1078, 987, 1080, 989),
    ],
    "Bellisseria_SLGI_Magic": [
        AreaBounds(1037, 947, 1038, 948),
        AreaBounds.from_slgi("1037/930-939"),
        AreaBounds(1038, 930, 1039, 934),
    ],
    "Bellisseria_SLGI_Primordial": [
        AreaBounds(1044, 953, 1045, 966),
        AreaBounds.from_slgi("1043/964-965"),
        AreaBounds.from_slgi("1042-1043/953-963"),
        AreaBounds.from_slgi("1041/953-962"),
        AreaBounds.from_slgi("1040/953-958"),
        AreaBounds.from_slgi("1035-1039/953"),
    ],
    "Bellisseria_SLGI_WaterParadise": [
        AreaBounds(1058, 967, 1063, 974),
        AreaBounds.from_slgi("1058-1062/975"),
        AreaBounds.from_slgi("1060-1061/976"),
        AreaBounds.from_slgi("1064-1068/992"),
        AreaBounds(1080, 990, 1081, 992),
        AreaBounds.from_slgi("1081/989"),
    ],
    "SecondNorway": [
        AreaBounds(1149, 1046, 1152, 1047),
        AreaBounds(1149, 1049, 1149, 1054),
    ],
}

DO_NOT_MAP_AREAS: Final[dict[str, AreaBounds]] = {
    "CH": AreaBounds(1102, 1199, 1104, 1201),        ### NOT interesting
    "SSP-15xx": AreaBounds(1155, 1379, 1165, 1383),  ### NOT interesting
    "SSP-40xx": AreaBounds(1182, 1371, 1187, 1377),  ### NOT interesting
}

# fmt: on


class _GetSupressed:
    @staticmethod
    def __contains__(item: str):
        area = KNOWN_AREAS[item]
        if isinstance(area, AreaDescriptor):
            return bool(area.excludes)
        return item in _SUPPRESS_FOR_AREAS

    @staticmethod
    def __getitem__(item: str):
        if isinstance(KNOWN_AREAS[item], AreaDescriptor):
            area: AreaDescriptor = KNOWN_AREAS[item]
            return list(area.excludes)
        return _SUPPRESS_FOR_AREAS[item]

    @staticmethod
    def items() -> Generator[tuple[str, list[AreaBounds]], None, None]:
        seen = set()
        for name, desc in KNOWN_AREAS.items():
            if isinstance(desc, AreaDescriptor):
                seen.add(name)
                yield name, list(desc.excludes)
        for name, exc in _SUPPRESS_FOR_AREAS.items():
            if name in seen:
                continue
            yield name, exc

    @staticmethod
    def get(item: str, default=None) -> Union[list[AreaBounds] | None]:
        area = KNOWN_AREAS[item]
        if isinstance(area, AreaDescriptor):
            return list(area.excludes)
        return _SUPPRESS_FOR_AREAS.get(item, default)


SUPPRESS_FOR_AREAS = _GetSupressed()
