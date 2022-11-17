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


### `mosaic_v3` Module

An executable module to generate mosaic map and nightlights map.

> **WARNING:** This module takes _HOURS_ to finish if you use the default range of `y_min=0` to `y_max=2000`! And you may have to re-run it several times
> for it to retrieve 'missing' tiles due to error during retrieval!

To see how to use it:

```shell
cd src
python -Xfrozen_modules=off -m mosaic_v3 [options] 
```

To see the options, use `--help`


### `sl-maptools` Module

A library of functions and classes used by the rest of the SL-Cartography package.

Not executable.


## Nomenclature

A **tile** is a location on the map, indicated by **coordinates**.

**Coordinates** is the pseudo-geo-coordinates on the world map, which follows the rules:
  * Increasing **X** towards the East (right)
  * Decreasing **X** towards the West (left)
  * Increasing **Y** towards the North (up)
  * Decreasing **Y** towards the South (down)

As you can see, for the **Y** dimension, it is opposite to **canvas coordinates**:

  * **Canvas X** starts at 0 on the left edge, increasing to the right
  * **Canvas Y** starts at 0 on the top edge, increasing to the bottom

A **tile** also means a graphic element that will be pasted to the **canvas** at
canvas coordinates that represents the correct location of coordinates in the map.

A **tile** can contain a **region** or a **void** (that is, no regions at the
location). A **region** is indicated then a **tile image** is returned by the
SL Map server.

Some map generation procedures subdivides the **tile** into **subtiles**.

A **subtile** is usually a **transform** of part of a **region**, or in other
words, a subtile is the result of some image processing involving part of the
tile image.

Some **transform** methods subdivides the tile image into multiple overlapping
**areas**/**subregions**. This is usually done by first subdividing the region
(tile image) into a lot of small **squares**/**pieces**, then consolidating
some squares/pieces into subtiles. For example:

  * For a 2x2 subtile arrangement, we subdivide the region into 2x2 squares,
    then consolidate each area of 1x1 square into a subtile.

    This will result in 2x2 non-overlapping areas, so each subtile stands
    alone and does not get influenced by adjacent subtiles.

  * For a 3x3 subtile arrangement, we subdivide the region into 16x16 squares,
    then consolidate each area of 6x6 square into a subtile.

    This will result in 3x3 overlapping areas, each area overlaping adjacent
    areas in a 1-square-wide **strip**. This means every subtile might be
    subtly influenced by adjacent subtiles.


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
