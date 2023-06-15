# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import sys

from pathlib import Path
from typing import Final

if sys.version_info < (3, 11):
    from typing_extensions import NotRequired, TypedDict
else:
    from typing import NotRequired, TypedDict

from ruamel.yaml import YAML

from sl_maptools import AreaBounds, AreaDescriptor

# fmt: off
_KNOWN_AREAS: Final[dict[str, AreaDescriptor]] = {
    # region ### Linden Continents - Bellisseria

    # region ## Original, self-made segmentation of Bellisseria area
    "Bellisseria_CM_South": AreaDescriptor(includes=AreaBounds(1038, 950, 1063, 977)),
    "Bellisseria_CM_West": AreaDescriptor(includes=AreaBounds(1023, 940, 1045, 977)),
    "Bellisseria_CM_Atolls": AreaDescriptor(includes=AreaBounds(1023, 928, 1032, 940)),
    "Bellisseria_CM_Annex": AreaDescriptor(includes=AreaBounds(1037, 930, 1053, 949)),
    "Bellisseria_CM_Central": AreaDescriptor(includes=AreaBounds(1058, 967, 1081, 1000)),
    "Bellisseria_CM_North": AreaDescriptor(includes=AreaBounds(1078, 987, 1100, 1024)),
    # endregion

    # region ## SLGI-assigned names / segmentation of the Belli. area
    "Bellisseria_SLGI_Forest": AreaDescriptor(
        includes=AreaBounds(1043, 950, 1063, 977),
        excludes=[
            AreaBounds(1063, 977, 1063, 977),  # Part of Belliseria Water Paradise
            AreaBounds(1038, 964, 1045, 977),  # Part of Belliseria Primordial / Victorian
            AreaBounds(1038, 963, 1044, 963),  # Part of Belliseria Primordial / Victorian
            AreaBounds(1038, 950, 1042, 962),  # Part of Belliseria Primordial / Victorian
            AreaBounds(1043, 955, 1043, 956),  # Part of Belliseria Primordial / Victorian
        ]
    ),
    "Bellisseria_SLGI_Victorian": AreaDescriptor(
        includes=AreaBounds(1024, 941, 1046, 966),
        excludes=[
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
    ),
    "Bellisseria_SLGI_Jeogeot": AreaDescriptor(
        includes=AreaBounds(1023, 928, 1035, 943),
        excludes=[
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
    ),
    "Bellisseria_SLGI_East": AreaDescriptor(
        includes=AreaBounds(1078, 987, 1100, 1024),
        excludes=[
            AreaBounds.from_slgi("1100/1005-1010"),
            AreaBounds(1078, 987, 1080, 989),
        ],
    ),
    "Bellisseria_SLGI_Magic": AreaDescriptor(
        includes=AreaBounds(1037, 930, 1053, 949),
        excludes=[
            AreaBounds(1037, 947, 1038, 948),
            AreaBounds.from_slgi("1037/930-939"),
            AreaBounds(1038, 930, 1039, 934),
        ]
    ),
    "Bellisseria_SLGI_Primordial": AreaDescriptor(
        includes=AreaBounds(1023, 953, 1045, 977),
        excludes=[
            AreaBounds(1044, 953, 1045, 966),
            AreaBounds.from_slgi("1043/964-965"),
            AreaBounds.from_slgi("1042-1043/953-963"),
            AreaBounds.from_slgi("1041/953-962"),
            AreaBounds.from_slgi("1040/953-958"),
            AreaBounds.from_slgi("1035-1039/953"),
        ],
    ),
    "Bellisseria_SLGI_Sakura": AreaDescriptor(includes=AreaBounds(1063, 992, 1072, 1000)),
    "Bellisseria_SLGI_WaterParadise": AreaDescriptor(
        includes=AreaBounds(1058, 967, 1081, 992),
        excludes=[
            AreaBounds(1058, 967, 1063, 974),
            AreaBounds.from_slgi("1058-1062/975"),
            AreaBounds.from_slgi("1060-1061/976"),
            AreaBounds.from_slgi("1064-1068/992"),
            AreaBounds(1080, 990, 1081, 992),
            AreaBounds.from_slgi("1081/989"),
        ],
    ),
    # endregion

    # region ## Commonly used Belli. names, used by BB & BBB

    "Bellisseria-Fantasseria": AreaDescriptor(
        includes=AreaBounds(1037, 930, 1053, 949),
        excludes=[
            AreaBounds(1037, 947, 1038, 948),
            AreaBounds.from_slgi("1037/930-939"),
            AreaBounds(1038, 930, 1039, 934),
        ]
    ),
    "Bellisseria-Sakurasseria": AreaDescriptor(
        includes=AreaBounds(1063, 992, 1072, 1000),
    ),
    "Bellisseria-Stiltlands": AreaDescriptor(
        includes=AreaBounds(1058, 967, 1081, 992),
        excludes=[
            AreaBounds(1063, 992, 1072, 992),  # Part of Sakurasseria
            AreaBounds(1079, 991, 1081, 992),  # Part of Newbrooke
            AreaBounds(1080, 990, 1081, 990),  # Part of Newbrooke
            AreaBounds(1081, 989, 1081, 989),  # Part of Newbrooke
            AreaBounds(1058, 967, 1063, 974),  # Part of Loglands
            AreaBounds(1058, 975, 1062, 975),  # Part of Loglands
            AreaBounds(1060, 976, 1061, 976),  # Part of Loglands
        ],
    ),


    # endregion

    # endregion

    # region ### Linden Continents - Non Bellisseria
    "Zindra": AreaDescriptor(includes=AreaBounds(1797, 1179, 1821, 1202)),
    "SansaraSnowlands": AreaDescriptor(includes=AreaBounds(1003, 979, 1018, 995)),
    "Sansara": AreaDescriptor(includes=AreaBounds(982, 978, 1038, 1012)),
    "SeaOfFables": AreaDescriptor(includes=AreaBounds(1015, 992, 1023, 999)),
    "BayCityPlains": AreaDescriptor(includes=AreaBounds(982, 999, 995, 1006)),
    "Sharp": AreaDescriptor(includes=AreaBounds(1159, 988, 1179, 1002)),
    "Heterocera": AreaDescriptor(includes=AreaBounds(991, 1012, 1014, 1036)),
    "Jeogeot": AreaDescriptor(includes=AreaBounds(1004, 897, 1039, 939)),
    "GaetaV": AreaDescriptor(includes=AreaBounds(1159, 1081, 1189, 1099)),
    "GaetaI": AreaDescriptor(includes=AreaBounds(1140, 1112, 1155, 1130)),
    "Satori": AreaDescriptor(includes=AreaBounds(1099, 1005, 1134, 1047)),
    "Corsica": AreaDescriptor(includes=AreaBounds(1100, 1082, 1159, 1100)),
    "Nautilus": AreaDescriptor(includes=AreaBounds(1106, 1047, 1138, 1081)),
    "Horizons": AreaDescriptor(includes=AreaBounds(1804, 1200, 1813, 1210)),
    "BlakeSea": AreaDescriptor(includes=AreaBounds(1131, 1048, 1148, 1054)),
    # endregion

    # region ### Premium Continents
    "EastPremium": AreaDescriptor(includes=AreaBounds(1192, 907, 1215, 926)),
    "SouthPremium-North": AreaDescriptor(includes=AreaBounds(1013, 811, 1028, 828)),
    "SouthPremium-Middle": AreaDescriptor(includes=AreaBounds(1000, 750, 1022, 768)),
    "SouthPremium-South": AreaDescriptor(includes=AreaBounds(1000, 500, 1022, 518)),
    # endregion

    # region ### User Continents
    "BlakeSeaSurrounding": AreaDescriptor(
        includes=AreaBounds(1131, 1036, 1152, 1061),
        excludes=[
            AreaBounds(1149, 1055, 1152, 1061),  # Second Norway
            AreaBounds(1150, 1049, 1152, 1054),  # Second Norway
            AreaBounds(1131, 1039, 1134, 1046),  # Satori
            AreaBounds(1133, 1047, 1134, 1047),  # Satori
            AreaBounds(1131, 1048, 1131, 1061),  # Nautilus / Citadel
            AreaBounds(1132, 1052, 1132, 1061),  # Nautilus
            AreaBounds(1133, 1055, 1134, 1061),  # Nautilus
            AreaBounds(1134, 1054, 1134, 1054),  # Nautilus
        ],
    ),
    "BlakeSeaSurroundingNoSuppress": AreaDescriptor(includes=AreaBounds(1131, 1036, 1152, 1061)),
    "SecondNorway": AreaDescriptor(
        includes=AreaBounds(1149, 1041, 1165, 1063),
        excludes=[
            AreaBounds(1149, 1046, 1152, 1047),
            AreaBounds(1149, 1049, 1149, 1054),
        ],
    ),
    "AzureIslands": AreaDescriptor(includes=AreaBounds(977, 959, 989, 966)),
    "EdenFruitIslands": AreaDescriptor(includes=AreaBounds(459, 1700, 481, 1720)),
    "Luxory": AreaDescriptor(includes=AreaBounds(621, 1033, 632, 1050)),
    "Caledon": AreaDescriptor(includes=AreaBounds(905, 1020, 909, 1025)),
    "PlayaIsles": AreaDescriptor(includes=AreaBounds(824, 1207, 831, 1217)),
    "Freedom": AreaDescriptor(includes=AreaBounds(750, 1013, 758, 1020)),
    "TuaruaFiji": AreaDescriptor(includes=AreaBounds(1131, 1064, 1149, 1082)),
    "Uhre": AreaDescriptor(includes=AreaBounds(860, 984, 865, 989)),
    "FantasyLands": AreaDescriptor(includes=AreaBounds(841, 1001, 844, 1010)),
    "SeabirdIslands": AreaDescriptor(includes=AreaBounds(686, 920, 692, 928)),
    "CoralOcean": AreaDescriptor(includes=AreaBounds(479, 1271, 485, 1280)),
    "Gooseberry": AreaDescriptor(includes=AreaBounds(669, 1423, 674, 1429)),
    # "TrinidadTobago": AreaDescriptor(includes=AreaBounds(902, 1372, 906, 1376)),
    "AllenCommunity": AreaDescriptor(includes=AreaBounds.from_slgi("902-906/1372-1376")),
    "NativeIslands": AreaDescriptor(includes=AreaBounds(733, 1367, 738, 1371)),
    "MauiIslandEstates": AreaDescriptor(includes=AreaBounds(548, 1137, 551, 1140)),
    "Rosehaven": AreaDescriptor(includes=AreaBounds(906, 1029, 909, 1034)),
    "TortugaIslands": AreaDescriptor(includes=AreaBounds(500, 1010, 504, 1013)),
    "SeductionEstate": AreaDescriptor(includes=AreaBounds(757, 926, 763, 932)),
    "AntiquityLand": AreaDescriptor(includes=AreaBounds(763, 909, 766, 913)),
    "NewHaven": AreaDescriptor(includes=AreaBounds(597, 1181, 603, 1184)),
    "TheGroveEstate": AreaDescriptor(includes=AreaBounds(1000, 1166, 1008, 1171)),
    "TheWastelands": AreaDescriptor(includes=AreaBounds(785, 1036, 787, 1039)),
    "CedarCreek": AreaDescriptor(includes=AreaBounds(849, 1342, 853, 1346)),
    "PlumIslandSoundEstate": AreaDescriptor(includes=AreaBounds(921, 1168, 923, 1171)),
    "AMEstate": AreaDescriptor(includes=AreaBounds(604, 1164, 609, 1169)),
    "CalasGaladhonPark": AreaDescriptor(includes=AreaBounds(709, 1110, 713, 1113)),
    "IsleOfWyrms": AreaDescriptor(includes=AreaBounds(545, 1059, 548, 1063)),
    "AmazonRiver": AreaDescriptor(includes=AreaBounds(832, 969, 835, 972)),
    "Baunatal": AreaDescriptor(includes=AreaBounds(715, 922, 718, 924)),
    "CrackDen": AreaDescriptor(includes=AreaBounds(742, 1389, 745, 1391)),
    "MadisonCounty": AreaDescriptor(includes=AreaBounds(850, 1320, 852, 1323)),
    "TempletonCove": AreaDescriptor(includes=AreaBounds(1027, 1240, 1030, 1242)),
    "Mythera": AreaDescriptor(includes=AreaBounds(720, 1324, 722, 1328)),
    "JunglesOfGor": AreaDescriptor(includes=AreaBounds(1097, 949, 1099, 951)),
    "Raglan": AreaDescriptor(includes=AreaBounds(1083, 1296, 1086, 1299)),
    "FairChang": AreaDescriptor(
        includes=AreaBounds(1103, 1048, 1110, 1060),
        excludes=[
            AreaBounds(1106, 1057, 1110, 1061),
            AreaBounds(1109, 1055, 1110, 1056),
            AreaBounds(1110, 1052, 1110, 1054),
        ]
    ),
    "MeisterbastlerKreis": AreaDescriptor(includes=AreaBounds.from_slgi("1105-1114/1382-1388")),
    # endregion
    # region ### User Continents - Tentative
    "GoreanLands": AreaDescriptor(includes=AreaBounds(1014, 1175, 1020, 1179)),
    "AngelManor": AreaDescriptor(includes=AreaBounds(1054, 1397, 1056, 1400)),
    "NakedEstates": AreaDescriptor(includes=AreaBounds(1038, 1161, 1042, 1163)),
    "WildWest": AreaDescriptor(includes=AreaBounds(963, 1145, 967, 1149)),
    "Babbage": AreaDescriptor(includes=AreaBounds(630, 1004, 633, 1007)),
    "Capitol": AreaDescriptor(includes=AreaBounds(641, 995, 645, 998)),
    "SunIslands": AreaDescriptor(includes=AreaBounds(876, 987, 878, 990)),
    "Mieville": AreaDescriptor(includes=AreaBounds(533, 1196, 537, 1202)),
    "Pirates1700": AreaDescriptor(includes=AreaBounds(940, 1174, 942, 1177)),
    "Coeur": AreaDescriptor(includes=AreaBounds(554, 1117, 559, 1124)),
    "SnugHarbor": AreaDescriptor(
        includes=AreaBounds(1146, 1052, 1149, 1056),
        excludes=AreaBounds(1146, 1056, 1146, 1056),
    ),
    "ASLMetaverse": AreaDescriptor(includes=AreaBounds(763, 915, 765, 917)),
    # ### Below this line, are areas with < 10 regions in a clump
    "Yumix": AreaDescriptor(includes=AreaBounds(653, 1245, 654, 1249)),
    "VWBPE": AreaDescriptor(includes=AreaBounds(1102, 1312, 1106, 1314)),
    "Maple": AreaDescriptor(includes=AreaBounds(878, 927, 882, 928)),
    "BlackBay": AreaDescriptor(includes=AreaBounds(615, 1058, 617, 1060)),
    "Schindleria": AreaDescriptor(includes=AreaBounds(527, 1027, 529, 1029)),
    "MayaLake": AreaDescriptor(includes=AreaBounds(979, 1198, 981, 1200)),
    "MacedoniaEstate": AreaDescriptor(includes=AreaBounds(540, 1182, 544, 1185)),
    "Bauer": AreaDescriptor(includes=AreaBounds(899, 1200, 902, 1202)),
    "Olni": AreaDescriptor(includes=AreaBounds(655, 1291, 658, 1293)),
    "Romanum": AreaDescriptor(includes=AreaBounds(747, 1079, 749, 1083)),
    "EndOfTime": AreaDescriptor(includes=AreaBounds(500, 1027, 503, 1030)),
    # endregion
    # region ### Special Areas
    "LindenEstateServices": AreaDescriptor(includes=AreaBounds(1025, 1014, 1031, 1016)),
    "MoleIslands": AreaDescriptor(includes=AreaBounds(1006, 971, 1011, 976)),
    # "SLBRegions": AreaDescriptor(includes=AreaBounds(390, 359, 402, 374)),
    "LR-160": AreaDescriptor(includes=AreaBounds(1187, 1206, 1190, 1210)),
    "LR-180": AreaDescriptor(includes=AreaBounds(1193, 1206, 1196, 1210)),
    "Preflight": AreaDescriptor(includes=AreaBounds(1296, 1193, 1299, 1196)),
    # "TheMists": AreaDescriptor(includes=AreaBounds(562, 734, 567, 739)),  ### Former site of Fantasy Faire 2023
    # TheMists disappeared in June 2023
    "PaleoQuest": AreaDescriptor(includes=AreaBounds(400, 392, 401, 400)),
    # "RFL2023": AreaDescriptor(includes=AreaBounds(503, 705, 554, 1621)),
    "RFL2023": AreaDescriptor(includes=AreaBounds(547, 705, 554, 716)),
    # "SLB2023": AreaDescriptor(includes=AreaBounds(386, 368, 403, 377)),
    "SLB2023": AreaDescriptor(includes=AreaBounds(386, 359, 403, 377)),
    # endregion
}

DO_NOT_MAP_AREAS: Final[dict[str, AreaBounds]] = {
    "CH": AreaBounds(1102, 1199, 1104, 1201),        ### NOT interesting
    "SSP-15xx": AreaBounds(1155, 1379, 1165, 1383),  ### NOT interesting
    "SSP-40xx": AreaBounds(1182, 1371, 1187, 1377),  ### NOT interesting
}

# fmt: on

KNOWN_AREAS: Final[dict[str, AreaDescriptor]] = {}


CoordBounds = list[str | list[int]]


class AreaDef(TypedDict):
    includes: CoordBounds
    excludes: NotRequired[CoordBounds]
    slgi_url: NotRequired[str]
    alternative_names: NotRequired[list[str]]
    notes: NotRequired[str]


def read_known_areas(yaml_file: Path):
    KNOWN_AREAS.clear()
    _data: dict[str, AreaDef]
    with yaml_file.open("rt") as fin:
        _data = YAML(typ="safe").load(fin)

    def _to_abounds(item) -> AreaBounds:
        if isinstance(item, str):
            return AreaBounds.from_slgi(item)
        if isinstance(item, list) and len(item) == 4:
            return AreaBounds(*item)
        raise ValueError(f"Don't understand this item: {item}")

    for _n, _d in _data.items():
        _incs = {_to_abounds(i) for i in _d["includes"]}
        _excs = {_to_abounds(i) for i in _d.get("excludes", [])}
        KNOWN_AREAS[_n] = AreaDescriptor(includes=_incs, excludes=_excs, name=_n)


read_known_areas(Path(__file__).with_suffix(".yaml"))
