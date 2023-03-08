# Second Life Cartography

A set of **Python 3.11** scripts to generate:
  * High-resolution maps of a certain area
  * Mosaic map of the (SL) world
  * 'Nightlights map' of the world

_'Nightlights map' is what you get if you snap a long-exposure aerial picture of an area
on Earth, with lights of houses, buildings, street lamps, vehicles on the road, sea vessels, etc.
highlighting the lay of the land. In my implementation, I modified the presentation a bit to
better emphasize connected regions, allowing you to easily see big connected landmasses._

> **Note:** **Python 3.11 is a requirement.**
> 
> This package _might_ run on older Python versions, but
> I developed and tested these scripts using Python 3.11, so I might have inadvertently
> used features only available on Python 3.11, rendering them unable to run on older Python
> versions. Sorry, I just don't have the time nor desire to make this package
> backwards-compatible, and I _will_ reject Pull Requests whose sole purpose is to make
> this package backwards-compatible.
> 
> You are, of course, free to fork this package and build upon it. Just remember to honor the
> Licenses used in the package.


## Installation

After doing a `git clone` of the repo, install packages listed in `pyproject.toml`

```shell
cd sl-cartography
python -m pip install . 
```

(Of course you should do that inside a virtualenv)


## Contents

### `cartographer` Module

An executable module to generate maps of Known Areas.

To see how to use it:

```shell
cd src
python -Xfrozen_modules=off -m cartographer [options] 
```

To see the options, use `--help`


### `cartographer.roadmapper` Module

An executable module to generate "Road Overlays" from one or more YAML files.

> A "Road Overlay" is a transparent PNG you can layer on top of a hi-res map generated
> by the `cartographer` module. Since it relies on how `cartographer` generated
> the maps, it is under the `cartographer` module and not standalone.

For the syntax of the YAML file(s),
please see `src/cartographer/roadmapper/README.md`

To see how to use the module:

```shell
cd src
python -Xfrozen_modules=off -m cartographer.roadmapper [options] 
```

To see the options, use `--help`


### `cartographer.roadmapper.parse_chat` Module

An executable module to parse chat transcript(s) into a YAML file that can be
consumed by `cartographer.roadmapper`

To see how to use it:

```shell
cd src
python -Xfrozen_modules=off -m cartographer.roadmapper.parse_chat [options] 
```

To see the options, use `--help`



### `mosaic_v3` Module

An executable module to generate mosaic map and nightlights map.

To see how to use it:

```shell
cd src
python -Xfrozen_modules=off -m mosaic_v3 [options] 
```

To see the options, use `--help`

> **WARNING:** This module takes _HOURS_ to finish if you use the default range of `y_min=0` to `y_max=2000`! And you may have to re-run it several times
> for it to retrieve 'missing' tiles due to error during retrieval!
> 
> Usually you will want to invoke it using `--ymin xxxx` where xxxx is about
> 200-300 rows lower than the previous invocation. So, start with, say
> `--ymin 1800`, then run again with `--ymin 1600` and so on to build the map
> gradually.


### `sl-maptools` Module

A library of functions and classes used by the rest of the SL-Cartography package.

Not executable.


## Nomenclature

**World** is the map of the whole Second Life world.

A **Region** is a named region in Second Life, or can be a void. The size is nominally 256m x 256m.
The location of a Region in the World is indicated using Coordinates (see below). A **RegionImage**
is the hi-res image of that Region.

A **Slab** is a rectangular set of Fascias/Tiles within a Region; Slabs can be overlapping.

A **Fascia** is a rectangular grouping of Tiles, smaller than a Slab.

A **Tile** is a 1m x 1m square within a region.

So a Region comprises 65536 tiles (256 x 256).

**Coordinates** is the pseudo-geo-coordinates on the world map, which follows the rules:
  * Increasing **X** towards the East (right)
  * Decreasing **X** towards the West (left)
  * Increasing **Y** towards the North (up)
  * Decreasing **Y** towards the South (down)

**Note:** There are actually several kinds of Coordinates:
  * Region Coordinates / Map Coordinates (in unit of regions), which pinpoints a region in the World Map
  * Global Coordinates (in unit of meters), which pinpoints a spot in the World Map
  * Local Coordinates (in unit of meters), which pinpoints a location within a Region relative to the Region's SouthWest corner.

The relation is as follows:

```
Global Coordinates = (Region Coordinates * 256) + Local Coordinates
```

**Canvas Coordinates** runs the opposite for the **Y** dimension:

  * **Canvas X** starts at 0 on the left edge, increasing to the right
  * **Canvas Y** starts at 0 on the top edge, increasing to the bottom

Again, the modifiers "global" or "region/map" or "local" can also be applied as needed to clarify when necessary.

**Note:** To differ, when we use the Geo Coordinates, we usually say "South", or "North", or "West", or "East", i.e.,
compass points. While when we use Canvas Coordinates, we usually say "down", or "up", or "left", or "right".

Some **transform** methods subdivides the Region image into multiple overlapping
**Slabs**. This is usually done by consolidating Tiles into Fascias, then group the
Fascias into Slabs; adjacent Slabs might share a row/column of SuperTiles, according
to the transform method.

For example:

  * For a 2x2 Slab arrangement, we subdivide the region into 2x2 Fascias, each Fascia
    containing 128 x 128 Tiles, then we put each Fascia into a Slab.

    This will result in 2x2 non-overlapping Slabs, so each Slab stands
    alone and does not get influenced by adjacent Slabs.

  * For a 3x3 Slab arrangement, we subdivide the region into 16x16 Fascias, each Fascia
    containing 16x16 Tiles; then we build the Slabs out of 6x6 Fascias.

    This will result in 3x3 overlapping Slabs, each Slab overlaping adjacent
    Slabs in a 1-Fascia-wide **strip**. This means every Slab might be
    subtly influenced by adjacent Slabs.


## Contributing

Create an issue and/or a Pull Requests.

As previously mentioned: Pull Requests whose purpose are _solely_ for
backward-compatibility with Python<3.11 _will be outright rejected_.

Also, please follow these guidelines:

* Code MUST be formatted using **Black** with the configuration as stated in `pyproject.toml`
* In addition, imports MUST be formatted using **isort** with the configuration as set in `pyproject.toml`

## Licenses

Mostly MPL-2.0, with some exceptions. Please see the `LICENSE` file for details.

Most notably, the usage of data & API of [GridSurvey](http://www.gridsurvey.com)
is licensed under [CC-BY-2.0-UK](https://creativecommons.org/licenses/by/2.0/uk/).
