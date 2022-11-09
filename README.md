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

### `cartographer`

An executable module to generate maps of Known Areas.

To see how to use it:

```shell
cd src
python -Xfrozen_modules=off -m cartographer [options] 
```

To see the options, use `--help`


### `mosaic`

An executable module to generate mosaic map and nightlights map.

> **WARNING:** This module takes _HOURS_ to finish! And you may have to re-run it several times
> for it to retrieve 'missing' tiles due to error during retrieval!

To see how to use it:

```shell
cd src
python -Xfrozen_modules=off -m mosaic [options] 
```

To see the options, use `--help`


### `sl-maptools`

A library of functions and classes used by the rest of the SL-Cartography package.

Not executable.

## Licenses

Mostly MPL-2.0, with some exceptions. Please see the `LICENSE` file for details.
