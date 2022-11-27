The `cartographer.roadmapper` module accepts input from two sources:

  * Chat Transcript
  * YAML file


## Chat Transcript Parsing

The chat transcript that will be processed will look like this:

```
<timestamp> PosRecorder: # <comment>
<timestamp> PosRecorder: <command> [<params>]
<timestamp> PosRecorder: <setting>: <value>
<timestamp> PosRecorder: <PosRecord_v3>
```

`<comment>` lines will be ignored silently.

`<timestamp>` is not used at the moment.

Unrecognized <command>/<setting> will emit a warning but will be ignored.

### Supported `<command>`s

#### `arc`

This is a special command.

An arc will be drawn through 3 points (i.e., 3 PosRecord's) directly following the command.

Any non-PosRecord entries in the chat transcript will be ignored and discarded silently.

The previous segment will also be ended/broken (similar to `break` command), so it is recommended to set the
beginning point of the arc right on the last point of the preceding segment.

The drawing mode will _always_ be solid (refer to `mode solid` below)

#### `break`

Breaks the line segment but keeps the next `PosRecord`s part of the same route.

This is useful for instance to record road grids in a city (example: Kama City
road grid)

#### `endroute` 

Indicates that a route has ended. A new `route` must be set before the parser
will accept a PosRecord_v3 object

#### `mode dashed` / `mode solid` / `mode rails`

Change the drawing strategy for following PosRecords.

This change will be effective until:
  * line segment is broken using `break` or `arc`, or
  * end of route is marked using `endroute`, or
  * a new route is started using `route: ___`, or
  * a new continent is started using `continent: ___`


### Supported `<setting>`s

#### `continent:`

Name of continent for the next routes.

One requirement: It is listed in `sl_maptools.knowns.KNOWN_AREAS`


#### `route:`

Name of the route for the next segments (set of PosRecord_v3)


#### `color:`

Explicitly sets the color of the next segment

The color must be one of the keys in the `ALL_COLORS` dict in `colors.py`, or
a comma-separated RGB value, with each value ranges from 0 to 255, like this:

```
PosRecorder: color: 255,0,0
PosRecorder: # The above will give intense red color
```


### PosRecord_v3

```
3;;Region_Name;;Parcel_Name;;<RegionCornerInInteger>;;<LocalPosInInteger>
```

The `3` in front represents the version of PosRecord.


## Cleaning up your Local Chat

If for instance you want to send your Local Chat to us (the maintainers)
for troubleshooting, you can use the following commands to clean up the
chat.

(Replace the `$CHAT_FILE` placeholder with the full path of your chat
transcript.)

### On Windows

Open Terminal or PowerShell, and enter the following:

```shell
Select-String -Path $CHAT_FILE -Pattern "PosRecorder:" | Select Line > filtered.txt
```

Then send the `filtered.txt` file to us.

### On Mac/Linux

Open Terminal, and enter the following:

```shell
grep "PosRecorder:" $CHAT_FILE > filtered.txt
```

Then send the `filtered.txt` file to us.


## YAML File Structure

```yaml
# Version marker is required, it is an integer
version: 1
road_data:
  - continent: Continent_1_Name
    routes:
      - route_name: Road_1_Name
        segments:
          # Please note that 'mode:' in this list MUST be uppercase!
          - mode: SOLID  # is one of "SOLID" or "DASHED" or "RAILS" or "ARC"
            color: null  # null here means use the auto-colors
            canv_points:
              # A list of pairs of CANVAS COORDINATES
              # If mode is "ARC" there will be EXACTLY 3 (three) canvas coordinates,
              # representing start of arc, a point along the arc (preferebly near the
              # middle for accuracy), and end of arc
              # All coordinates are in float, the drawing logic will perform rounding
              # to integer as needed. 
              - [1.0, 1.1]
              # Three digits behind decimal point is enough. More digits do not increase
              # precision in a perceptible way.
              - [2.011, 2.342]
          - mode: DASHED
            color: [255, 255, 0]  # if explicitly specified, this color will be used
            points:
              - [3.564, 3.22]
              - [4.0, 4.3]
          - mode: SOLID
            color: null
            points:
              # You can also just write the coordinates in integer. They will be converted
              # to float upon consumption
              - [5, 5]
              - [6, 6]
      - route_name: Road_2_Name  # route/road names in one continent must be unique
        segments:
          - ... and so on
  - continent: Continent_2_Name
    routes:
      - route_name: Road_1_Name  # road names are only required to be continent-unique
        segments:
          - ... and so on ...
```
