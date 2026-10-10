# Geospatial File Measurement API

A backend service using either Django or FastAPI that accepts a geospatial file, processes the features within it, and returns measurement information.
The service should accept either:
· Shapefile
· KML

## Setup

Needs Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 for the upload page (it shows the file info and measurements and can download them as CSV or JSON). 
The interactive API docs are at http://127.0.0.1:8000/docs.

Run the tests with `pytest`.

Uploaded files and results are stored under `./data` (change with the `GEO_DATA_DIR` environment variable).

## API

| Method | Path | What it does |
|---|---|---|
| GET | `/api/files/` | List uploaded files |
| GET | `/api/files/{id}/` | Info about one file |
| GET | `/api/files/{id}/features/` | Every feature: id, geometry type, geometry, CRS, properties |
| GET | `/api/files/{id}/measurements/` | Area / length per feature |

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

### Measurements

The measurements output will be shown when file is uploaded in "http://127.0.0.1:8000" in table format. The result can be downloaded in json or csv file.

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
app/main.py              HTTP endpoints, saving uploads, reading and writing result files
app/geo.py               reading files, CRS handling, measurement
app/static/index.html    home page (upload, results table, downloads)
tests/                   unit tests for the maths and an end-to-end upload test
data/                    created at runtime: one folder per upload
```
The code has three layers:

Client layer: the home page and the /docs page. Both only talk to the API.
API layer (main.py): receives requests, validates them, calls the processing layer and returns JSON. It does no geospatial work itself.
Processing layer (geo.py): reads files and calculates measurements. It knows nothing about HTTP, so it can be tested on its own.


**File processing.** 
1. The client sends POST /api/files/ with a .zip or .kml file.
2. The API rejects any other extension with 415.
3. It creates a unique id and saves the file to data/{id}/.
4. read_layers() opens the file. For a zip it checks that no entry would be written outside the folder, unzips it and finds every .shp. For a KML it reads each layer. A shapefile with no CRS is rejected, because the CRS can’t be guessed safely. A KML with no CRS is treated as WGS84.
5. extract_features() turns each row into a feature with its index, geometry type, geometry, CRS and properties. Altitude values are dropped.
6. Each feature is measured (section 4).
7. The result is written to data/{id}/result.json, and the temporary unzipped files are deleted.
8. The API returns the file information: id, filename, feature count, CRS and status.
If reading fails, the status is saved as FAILED and the API returns 422 with the reason.

**Measurement.** 
For each feature, measure() works by geometry type:
  Polygon or MultiPolygon: calculate the area in square metres.  
  LineString or MultiLineString: calculate the length in metres.
  Point or MultiPoint: no measurement is needed, so the result is a short note.
  Any other type, such as GeometryCollection: return a note saying it isn’t supported. A bad feature never stops the rest of the file.

For polygons and lines, the steps are:
1. Transform the geometry from the file’s CRS to WGS84.
2. Take the centroid and choose the UTM zone it falls in.
3. Transform the geometry to that UTM zone, where units are metres.
4. Read the area or length from the projected geometry.

**CRS handling.** 
Area and length are never calculated in degrees, because a degree of longitude covers a different distance at every latitude. The CRS of each feature is stored with it. Files in any CRS work, because the first step is always a conversion to WGS84.

## Design decisions

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
- Upload size limits and authentication.
