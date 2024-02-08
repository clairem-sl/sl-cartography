# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import shutil
import signal
import time
from contextlib import contextmanager
from typing import IO, TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from sl_maptools import SupportsSet

try:
    # noinspection PyCompatibility
    import tomllib
except ModuleNotFoundError:
    # noinspection PyUnresolvedReferences
    import tomli as tomllib

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


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


ValueTreeOnNotFound = Literal["raise"] | Literal["..."] | Literal["ellipsis"] | Literal["none"]


class ValueTree:
    """Wraps around a dict to provide access to dict values via object attributes"""

    def __init__(self, data: dict, *, on_not_found: ValueTreeOnNotFound = "raise"):
        """
        :param data: The dict to be wrapped
        :param on_not_found: What to do if attribute is not found. One of "raise" (raises KeyError), "..."/"ellipsis"
        (returns Ellipsis), or "none" (returns None). Default is "raise"
        """
        if on_not_found not in {"raise", "...", "ellipsis", "none"}:
            raise ValueError("on_not_found must be one of raise/.../ellipsis/none")
        self.__data = data
        self.__notfound: ValueTreeOnNotFound = on_not_found

    def __getattr__(self, item: str):
        if item not in self.__data:
            if self.__notfound == "raise":
                raise KeyError(f"Not Found: {item}")
            if self.__notfound == "none":
                return None
            return Ellipsis
        value = self.__data[item]
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return ValueTree(value, on_not_found=self.__notfound)
        if isinstance(value, Sequence):
            return self.__process_seq(value)
        return value

    def __getitem__(self, item: str):
        return self.__getattr__(item)

    def __process_seq(self, seq: Sequence) -> list:
        rslt = []
        for thing in seq:
            if not isinstance(thing, str) and isinstance(thing, Sequence):
                rslt.append(self.__process_seq(thing))
            elif isinstance(thing, dict):
                rslt.append(ValueTree(thing, on_not_found=self.__notfound))
            else:
                rslt.append(thing)
        return rslt

    def __repr__(self):
        return f"{self.__class__.__name__}({self.__data!r})"

    def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
        """Get a value given a key, returning default if key not found"""
        _prev_nf = self.__notfound
        self.__notfound = "raise"
        try:
            value = self.__getattr__(key)
        except KeyError:
            value = default
        finally:
            self.__notfound = _prev_nf
        return value


class NamesConfig(Protocol):
    """Attributes for the [names] section of config.toml"""

    dir: str
    db: str
    lock: str
    log: str
    progress: str


class MapsConfig(Protocol):
    """Attributes for the [maps] section of config.toml"""

    dir: str
    lock: str
    log: str
    progress: str


class MosaicConfig(Protocol):
    """Attributes for the [mosaic] section of config.toml"""

    dir: str
    domc_db: str


class NightlightsConfig(Protocol):
    """Attributes for the [nightlights] section of config.toml"""

    dir: str


class GridSectorsConfig(Protocol):
    """Attributes for the [nightlights] section of config.toml"""

    dir: str


class AreasConfig(Protocol):
    """Attributes for the [areas] section of config.toml"""

    dir: str
    """Directory to store Area Maps"""
    region_areas_db: str
    """YAML file containing a map of region names to a list of areas the region is included in"""


class FontSpec(Protocol):
    """Attributes to define a font. Analogous to PIL.ImageFont attributes"""

    font: str
    size: int
    index: int
    encoding: str
    variant: str
    overdraw: bool


class LatticeConfig(Protocol):
    """Attributes for the [grids] section of config.toml"""

    name: FontSpec
    coord: FontSpec


class BonnieConfig(Protocol):
    """Attribues for the [bonnie] section of config.toml"""

    dir: str
    db: str
    url: str
    maxage: int


class AnalysisConfig(Protocol):
    """Attributes for the [analysis] section of config.toml"""

    dir: str
    """Directory to store results from Analysis modules"""
    clumps_db: str
    """Pickle file containing the result of clump analysis, containing a list of sets of coordinates"""


class SLMapToolsConfig(Protocol):
    """Representation of configuration in config.toml"""

    names: NamesConfig
    maps: MapsConfig
    mosaic: MosaicConfig
    nightlights: NightlightsConfig
    gridsectors: GridSectorsConfig
    areas: AreasConfig
    lattice: LatticeConfig
    bonnie: BonnieConfig
    analysis: AnalysisConfig
    """Configuration for Analysis modules"""


class ConfigReader(SLMapToolsConfig):
    """Reads configuration from config.toml"""

    def __init__(self, config_file: str | Path):
        """
        :param config_file: Configuration file
        """
        self._cfg_file = Path(config_file)
        with self._cfg_file.open("rb") as fin:
            self._cfg_dict = tomllib.load(fin)
        self._cfg_tree = ValueTree(self._cfg_dict, on_not_found="none")

    def __getattr__(self, item: str):
        return getattr(self._cfg_tree, item)

    def __getitem__(self, item: str):
        return self._cfg_tree[item]

    def __repr__(self):
        return f"{self.__class__.__name__}({self._cfg_file!r})"


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
