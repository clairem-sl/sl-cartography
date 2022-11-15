# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pathlib import Path
import appdirs


STATE_DIR = Path(appdirs.site_data_dir("sl-cartography"))
STATE_FILE_PATH = STATE_DIR / "mosaic-state-v3.msgp"

WORKERS = 10

SAVE_DIR = Path(r"~\Pictures\SLMap").expanduser().absolute()
NIGHTLIGHTS_PATH = SAVE_DIR / "world-nightlights-3.png"
MOSAIC_PATH = SAVE_DIR / "world-mosaic-3.png"

WORLD_WIDTH = 2001
WORLD_HEIGHT = 2001
