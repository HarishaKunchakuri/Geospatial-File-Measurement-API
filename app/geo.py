"""Reading geospatial files and measuring the features in them."""
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform


class BadFile(Exception):
    """Raised when an uploaded file cannot be turned into features."""


def unzip(zip_path: Path, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                # refuse entries that would be written outside the folder
                if name.startswith("/") or ".." in Path(name).parts:
                    raise BadFile("Zip contains an unsafe path")
            z.extractall(folder)
    except zipfile.BadZipFile:
        raise BadFile("File is not a valid zip archive")


def read_layers(path: Path, work_dir: Path) -> list:
    """Return a list of GeoDataFrames, one per layer found in the file."""
    if path.suffix.lower() == ".zip":
        unzip(path, work_dir)
        shapefiles = sorted(work_dir.rglob("*.shp"))
        if not shapefiles:
            raise BadFile("The zip does not contain a .shp file")
        sources = shapefiles
        is_kml = False
    else:
        sources = [path]
        is_kml = True

    layers = []
    for source in sources:
        try:
            for name in [row[0] for row in pyogrio.list_layers(source)]:
                gdf = gpd.read_file(source, layer=name)
                if len(gdf) == 0:
                    continue
                if gdf.crs is None:
                    if not is_kml:
                        raise BadFile(f"{source.name} has no CRS (is the .prj file missing?)")
                    gdf = gdf.set_crs("EPSG:4326")  # KML is always WGS84
                layers.append(gdf)
        except BadFile:
            raise
        except Exception as e:
            raise BadFile(f"Could not read {source.name}: {e}")

    if not layers:
        raise BadFile("No features found in the file")
    return layers


def crs_name(crs) -> str:
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.name


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG code of the UTM zone that contains the point."""
    zone = min(int((lon + 180) // 6) + 1, 60)
    return (32600 if lat >= 0 else 32700) + zone


def measure(geom, crs) -> dict:
    """Area for polygons, length for lines, nothing for points.

    Degrees are never measured directly: the geometry goes to WGS84, then to
    the UTM zone around its centroid, and the measurement is taken in metres.
    """
    kind = geom.geom_type
    is_polygon = kind in ("Polygon", "MultiPolygon")
    is_line = kind in ("LineString", "MultiLineString")

    if kind in ("Point", "MultiPoint"):
        return {"note": "No measurement needed for points"}
    if not (is_polygon or is_line):
        return {"note": f"Measurement not supported for {kind}"}

    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    wgs84 = transform(to_wgs84.transform, geom)
    centre = wgs84.centroid

    utm = utm_epsg(centre.x, centre.y)
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{utm}", always_xy=True)
    flat = transform(to_utm.transform, wgs84)

    if is_polygon:
        return {"area_sq_m": round(flat.area, 2), "projected_crs": f"EPSG:{utm}"}
    return {"length_m": round(flat.length, 2), "projected_crs": f"EPSG:{utm}"}


def extract_features(layers: list) -> tuple:
    """Return (features, crs_label). Each feature carries its own measurements."""
    features = []
    labels = []

    for gdf in layers:
        label = crs_name(gdf.crs)
        if label not in labels:
            labels.append(label)

        attributes = gdf.drop(columns=gdf.geometry.name)
        rows = json.loads(attributes.to_json(orient="records", date_format="iso"))
        if len(rows) != len(gdf):  # layer with no attribute columns
            rows = [{} for _ in range(len(gdf))]

        for geom, props in zip(gdf.geometry, rows):
            feature = {
                "id": len(features),
                "geometry_type": None,
                "crs": label,
                "geometry": None,
                "properties": props,
                "measurements": {"note": "Feature has no geometry"},
            }
            if geom is not None and not geom.is_empty:
                geom = shapely.force_2d(geom)
                feature["geometry_type"] = geom.geom_type
                feature["geometry"] = mapping(geom)
                try:
                    feature["measurements"] = measure(geom, gdf.crs)
                except Exception as e:
                    feature["measurements"] = {"note": f"Could not measure: {e}"}
            features.append(feature)

    return features, labels[0] if len(labels) == 1 else "MIXED"
