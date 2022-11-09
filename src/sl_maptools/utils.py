# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import shutil
from pathlib import Path


def make_backup(the_file: Path, levels: int = 2):
    if not the_file.exists():
        return
    suff = the_file.suffix
    # prev0 is temporary; the loop will rename it to prev1
    shutil.copy(the_file, the_file.with_suffix(".prev0" + suff))
    for n in range(levels, 0, -1):
        prev_n = the_file.with_suffix(f".prev{n}{suff}")
        prev_b = the_file.with_suffix(f".prev{n-1}{suff}")
        if prev_b.exists():
            prev_n.unlink(missing_ok=True)
            prev_b.rename(prev_n)


class QuietablePrint:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def __call__(self, *args, **kwargs):
        if not self.quiet:
            print(*args, **kwargs)
