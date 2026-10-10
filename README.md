# Geospatial File Measurement API

A small FastAPI service. You upload a zipped Shapefile or a KML file, it reads every
feature, and it gives you back the feature details plus area (polygons) and length (lines)
in metres.

## Setup

Needs Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 for the upload page (it shows the file info and measurements and can download them as CSV or JSON). The interactive API docs are at
http://127.0.0.1:8000/docs.

Run the tests with `pytest`.

Uploaded files and results are stored under `./data` (change with the `GEO_DATA_DIR`
environment variable).

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/api/files/` | Upload a `.zip` (shapefile) or `.kml` and process it |
| GET | `/api/files/` | List uploaded files |
| GET | `/api/files/{id}/` | Info about one file |
| GET | `/api/files/{id}/features/` | Every feature: id, geometry type, geometry, CRS, properties |
| GET | `/api/files/{id}/measurements/` | Area / length per feature |
| DELETE | `/api/files/{id}/` | Remove a file and its results |

### Upload

```bash
curl -F "file=@samples/parcels.kml" http://127.0.0.1:8000/api/files/
```

```json
{
  "id": "9f2c0d6e1b7a4c0e8a3d5b61f4c27e90",
  "filename": "parcels.kml",
  "feature_count": 4,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null
}
```

Wrong extension gives `415`. A file that cannot be read (corrupt zip, no `.shp` inside,
missing `.prj`) gives `422` with the reason.

### Measurements

```bash
curl http://127.0.0.1:8000/api/files/<id>/measurements/
```

```json
[
  {"id": 0, "geometry_type": "Polygon", "area_sq_m": 1210552.31, "projected_crs": "EPSG:32643"},
  {"id": 2, "geometry_type": "LineString", "length_m": 5452.7, "projected_crs": "EPSG:32643"},
  {"id": 3, "geometry_type": "Point", "note": "No measurement needed for points"}
]
```

(Numbers above are illustrative.)

Geometry types that can't be measured (for example a GeometryCollection) come back with a
`note` instead of an error.

## Architecture

```
app/static/   the small HTML upload page served at /
app/main.py   HTTP endpoints, saving uploads, reading/writing result files
app/geo.py    reading files, CRS handling, measuring
tests/        unit tests for the maths and an end-to-end upload test
```

**File processing.** The upload is saved to `data/<id>/`. A zip is unpacked (entries that
would escape the folder are rejected) and every `.shp` in it is read; a KML is read layer by
layer. Each row becomes a feature with an index, geometry type, GeoJSON geometry, CRS and
attributes. Altitude values (KML often has them) are dropped. The finished result is
written to `data/<id>/result.json`, and the GET endpoints just read that file.

**Measurement.** For each polygon or line: convert to WGS84, find the centroid, pick the UTM
zone for that centroid, convert to that zone, then use shapely's `.area` / `.length`. Points
need nothing. Other types are reported as unsupported.

**CRS handling.** Degrees are never measured directly. Files in any CRS work, since each
geometry is first converted to WGS84. KML is always WGS84. A shapefile without a `.prj` is
rejected rather than guessed.

## Design decisions

- **Per-feature UTM zone instead of one zone for the file.** A file can cover several zones;
  choosing per feature keeps each measurement as accurate as UTM allows.
- **UTM instead of an equal-area projection.** UTM is easy to pick automatically and is
  accurate to roughly 0.1% for lengths within a zone. An equal-area CRS (e.g. a Lambert
  azimuthal centred on the feature) would be better for large areas, and geodesic
  calculations with `pyproj.Geod` avoid projections completely; I kept UTM for simplicity.
- **JSON files instead of a database.** The data is write-once and read-many, and a
  per-upload JSON file keeps setup to zero. The cost is that listing and filtering don't
  scale; see future scope.
- **Processing happens inside the upload request.** Simpler than a job queue; fine for files
  of normal survey size.
- **FastAPI over Django.** Less boilerplate for a small API, and automatic `/docs`.

## What I learned

- Shapefile and KML differ in how they carry CRS: KML is implicitly WGS84, a shapefile
  depends on a sidecar `.prj` that is easy to lose.
- Area computed in degrees is meaningless, and the error depends on latitude, so the
  projected step is not optional.
- Zip uploads need checking before extraction.

## Future scope

- Store results in PostgreSQL/PostGIS and add paging and filtering.
- Move processing to a background worker with status polling for large files.
- Geodesic measurement option (and a warning for features that span several UTM zones or
  cross the antimeridian).
- Support GeoJSON and GPKG, and CSV/GeoJSON export of the results.
- Upload size limits and authentication.
