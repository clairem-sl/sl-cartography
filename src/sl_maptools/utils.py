# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import shutil
import signal
import time
from contextlib import contextmanager
from typing import IO, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pathlib import Path
    from sl_maptools import SupportsSet


def make_backup(the_file: Path, levels: int = 2) -> None:
    """
    Make a backup of a file if exists. The original will be kept.

    :param the_file: Path of the file to backup
    :param levels: Maximum backup level. Older backups will be removed.
    """
    if not the_file.exists():
        return
    suff = the_file.suffix
    # prev0 is temporary; the loop will rename it to prev1
    shutil.copy(the_file, the_file.with_suffix(".prev0" + suff))
    for n in range(levels, 0, -1):
        prev_n = the_file.with_suffix(f".prev{n}{suff}")
        prev_b = the_file.with_suffix(f".prev{n-1}{suff}")
        if prev_b.exists():
            prev_b.replace(prev_n)


class QuietablePrint:
    """Wrapper around print() function that allows quick quieting + different defaults"""

    def __init__(self, quiet: bool = False, flush: bool = False):
        """
        :param quiet: If True, then don't actually print anything
        :param flush: Default value of `flush` kwarg
        """
        self.quiet = quiet
        self.flush = flush

    def __call__(
        self,
        *values: object,
        sep: Optional[str] = "",
        end: Optional[str] = "\n",
        file: Optional[IO] = None,
        flush: Optional[bool] = ...,
    ) -> None:
        """Emulates call to the print() function"""
        if flush is Ellipsis:
            flush = self.flush
        if not self.quiet:
            print(*values, sep=sep, end=end, file=file, flush=flush)


@contextmanager
def handle_sigint(interrupt_flag: SupportsSet) -> None:
    """
    A context manager that provides SIGINT handling, and restore original handler upon exit
    """

    def _handler(_, __) -> None:  # noqa: ANN001
        if interrupt_flag.is_set():
            return
        interrupt_flag.set()
        print("\n### USER INTERRUPT ###")
        print("Cleaning up in-flight job (if any)...", flush=True)

    orig_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handler)
    yield
    time.sleep(1)
    signal.signal(signal.SIGINT, orig_sigint)
