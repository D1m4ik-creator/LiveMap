from dataclasses import dataclass

from livemap.api.errors import APIError


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float

    @property
    def width(self) -> float:
        return self.east - self.west if self.west <= self.east else 360 - self.west + self.east

    @property
    def height(self) -> float:
        return self.north - self.south

    @property
    def crosses_antimeridian(self) -> bool:
        return self.west > self.east


def parse_bbox(value: str, zoom: int) -> BBox:
    try:
        west, south, east, north = (float(part) for part in value.split(","))
    except (ValueError, TypeError) as exc:
        raise APIError("invalid_bbox", "bbox must be west,south,east,north", 400) from exc
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise APIError("invalid_bbox", "Longitude must be within [-180, 180]", 400)
    if not (-90 <= south < north <= 90):
        raise APIError("invalid_bbox", "Latitude bounds are invalid", 400)
    bbox = BBox(west, south, east, north)
    if bbox.width <= 0 or bbox.width > 360:
        raise APIError("invalid_bbox", "Longitude bounds are invalid", 400)
    if zoom >= 9 and (bbox.width > 20 or bbox.height > 20):
        raise APIError("bbox_too_large", "bbox is too large for this zoom", 400)
    return bbox
