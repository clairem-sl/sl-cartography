#  This Source Code Form is subject to the terms of the Mozilla Public
#  License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
#  Copyright (C) 2023, Claire Morgenthau
from __future__ import annotations

from pathlib import Path

from sl_maptools import CoordType
from sl_maptools.image_processing import RGBTuple

DomColors = dict[int, list[RGBTuple]]
CalcResultType = tuple[CoordType, Path, DomColors]
