import os
import tempfile

os.environ["GEO_DATA_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402
from shapely.geometry import LineString, Point, box  # noqa: E402

from app.geo import measure, utm_epsg  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>plot</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
    77.000,12.000 77.010,12.000 77.010,12.010 77.000,12.010 77.000,12.000
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>road</name><LineString><coordinates>
    77.000,12.000 77.050,12.000
  </coordinates></LineString></Placemark>
  <Placemark><name>well</name><Point><coordinates>77.005,12.005</coordinates></Point></Placemark>
</Document></kml>"""


def test_utm_zone():
    assert utm_epsg(77.6, 12.9) == 32643
    assert utm_epsg(151.2, -33.9) == 32756


def test_polygon_area_is_in_metres_not_degrees():
    m = measure(box(77.0, 12.0, 77.01, 12.01), "EPSG:4326")
    assert 1.18e6 < m["area_sq_m"] < 1.23e6


def test_line_length():
    m = measure(LineString([(0, 0), (0.1, 0)]), "EPSG:4326")
    assert abs(m["length_m"] - 11132) < 60


def test_point_and_unsupported():
    assert "No measurement" in measure(Point(77, 12), "EPSG:4326")["note"]


def test_upload_flow():
    r = client.post("/api/files/", files={"file": ("survey.kml", KML)})
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["status"] == "COMPLETED" and info["feature_count"] == 3
    assert info["crs"] == "EPSG:4326"

    fid = info["id"]
    assert client.get(f"/api/files/{fid}/").json()["filename"] == "survey.kml"

    feats = client.get(f"/api/files/{fid}/features/").json()
    assert [f["geometry_type"] for f in feats] == ["Polygon", "LineString", "Point"]

    ms = client.get(f"/api/files/{fid}/measurements/").json()
    assert ms[0]["area_sq_m"] > 1e6 and ms[1]["length_m"] > 5000


def test_errors():
    assert client.post("/api/files/", files={"file": ("a.txt", b"x")}).status_code == 415
    assert client.post("/api/files/", files={"file": ("a.zip", b"x")}).status_code == 422
    assert client.get("/api/files/nothing/").status_code == 404
