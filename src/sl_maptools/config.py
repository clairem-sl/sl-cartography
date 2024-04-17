# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from __future__ import annotations

import tomllib
from collections.abc import Hashable, Sequence
from pathlib import Path
from typing import Any, Final, Literal, Protocol

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

    def get(self, key: str, default: Hashable = None) -> Any:  # noqa: ANN401
        """Get a value given a key, returning default if key not found"""
        _prev_nf = self.__notfound
        self.__notfound = "raise"
        try:
            value = getattr(self, key)
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
    connection_limit: int
    semaphore_multiplier: float


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
    db_regions: str
    url: str
    maxage: int


class AnalysisConfig(Protocol):
    """Attributes for the [analysis] section of config.toml"""

    dir: str
    """Directory to store results from Analysis modules"""
    clumps_db: str
    """Pickle file containing the result of clump analysis, containing a list of sets of coordinates"""


class InfoConfig(Protocol):
    """Attributes for the [info] section of config.toml"""

    author: str
    """Name of author"""
    comment: str
    """Any free-text comment; usually "SPDX-License-Identifier:" followed by an SPDX license code"""
    license: str
    license_url: str
    license_spdx: str


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
    info: InfoConfig


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


class DelayedConfigReader(SLMapToolsConfig):
    """Reads configuration from config.toml, but only after first attribute access"""

    def __init__(self, config_file: str | Path):
        """
        :param config_file: Configuration file
        """
        self._cfg_file = Path(config_file)
        self._cfg_tree: ValueTree | None = None

    def __read(self) -> None:
        with self._cfg_file.open("rb") as fin:
            _cfg_dict = tomllib.load(fin)
        self._cfg_tree = ValueTree(_cfg_dict, on_not_found="none")

    def __getattr__(self, item: str):
        if self._cfg_tree is None:
            self.__read()
        return getattr(self._cfg_tree, item)

    def __getitem__(self, item: str):
        if self._cfg_tree is None:
            self.__read()
        return self._cfg_tree[item]

    def __repr__(self):
        return f"{self.__class__.__name__}({self._cfg_file!r})"


DefaultConfig: Final[SLMapToolsConfig] = DelayedConfigReader("config.toml")  # pylint: disable=invalid-name
