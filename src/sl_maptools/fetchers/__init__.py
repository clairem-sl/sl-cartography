from sl_maptools import MapCoord


class FetcherConnectionError(ConnectionError):
    def __init__(
        self, *args, internal_errors: list[Exception] = None, coord: MapCoord = None
    ):
        super(FetcherConnectionError, self).__init__(*args)
        self.internal_errors = internal_errors or []
        self.coord = coord

    def __str__(self):
        return f"MapConnectionError({self.coord.x}, {self.coord.y}): {self.internal_errors}"
