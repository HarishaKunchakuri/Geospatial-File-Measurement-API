import json
import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse

from app import geo

DATA_DIR = Path(os.environ.get("GEO_DATA_DIR", "data"))
ALLOWED = {".zip", ".kml"}

# docs_url=None switches off the built-in /docs page; a customised one is defined below
app = FastAPI(title="Geospatial File Measurement API", docs_url=None)

DOCS_CSS = """
body { background: #fff; }
/* hide version badge, OAS badge, openapi.json link and the Schemas section */
.swagger-ui .info .title small,
.swagger-ui .info .link,
.swagger-ui .info .main a,
.swagger-ui section.models,
.swagger-ui .copy-to-clipboard,
.swagger-ui .opblock-summary-method,
.swagger-ui .opblock-summary-path,
.swagger-ui .opblock-summary-path__deprecated { display: none !important; }

/* rename the "Try it out" button */
.swagger-ui .btn.try-out__btn:not(.cancel) { font-size: 0; }
.swagger-ui .btn.try-out__btn:not(.cancel)::after { content: "Click to edit"; font-size: 14px; }

/* black and white only */
.swagger-ui .info .title,
.swagger-ui .opblock-tag { color: #000; }
.swagger-ui .opblock-tag { border-bottom-color: #000; }

.swagger-ui .opblock.opblock-get,
.swagger-ui .opblock.opblock-post,
.swagger-ui .opblock.opblock-delete { background: #fff; border-color: #000; }
.swagger-ui .opblock.opblock-get .opblock-summary,
.swagger-ui .opblock.opblock-post .opblock-summary,
.swagger-ui .opblock.opblock-delete .opblock-summary { border-color: #000; }

.swagger-ui .btn.execute { background-color: #000; border-color: #000; color: #fff; }
.swagger-ui .btn.try-out__btn,
.swagger-ui .btn.cancel { background: #fff; border-color: #000; color: #000; }
"""


@app.get("/docs", include_in_schema=False)
def docs():
    page = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title,
        swagger_ui_parameters={
            "defaultModelsExpandDepth": -1,   # also collapses Schemas
        },
    )
    html = page.body.decode().replace("</head>", f"<style>{DOCS_CSS}</style></head>")
    return HTMLResponse(html)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


def result_file(file_id: str) -> Path:
    return DATA_DIR / file_id / "result.json"


def load(file_id: str) -> dict:
    # ids are uuid hex strings; anything else cannot exist (and must not touch the disk)
    if not re.fullmatch(r"[0-9a-f]{32}", file_id) or not result_file(file_id).exists():
        raise HTTPException(status_code=404, detail="File not found")
    return json.loads(result_file(file_id).read_text())


def info_of(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "features"}


@app.post("/api/files/", status_code=201, summary="File Upload")
def upload(file: UploadFile = File(...)):
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=415, detail="Upload a .zip (shapefile) or .kml file")

    file_id = uuid.uuid4().hex
    folder = DATA_DIR / file_id
    folder.mkdir(parents=True)
    saved = folder / f"upload{ext}"
    with saved.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    result = {"id": file_id, "filename": name, "feature_count": 0,
              "crs": None, "status": "FAILED", "error": None, "features": []}
    try:
        layers = geo.read_layers(saved, folder / "unzipped")
        result["features"], result["crs"] = geo.extract_features(layers)
        result["feature_count"] = len(result["features"])
        result["status"] = "COMPLETED"
    except geo.BadFile as e:
        result["error"] = str(e)
    finally:
        shutil.rmtree(folder / "unzipped", ignore_errors=True)

    result_file(file_id).write_text(json.dumps(result))
    if result["status"] == "FAILED":
        raise HTTPException(status_code=422, detail=f"{result['error']} (id: {file_id})")
    return info_of(result)

@app.get("/api/files/{file_id}/", summary="File Info")
def file_info(file_id: str):
    return info_of(load(file_id))


@app.get("/api/files/{file_id}/features/", summary="Features")
def features(file_id: str):
    return load(file_id)["features"]


@app.get("/api/files/{file_id}/measurements/", summary="Measurements")
def measurements(file_id: str):
    result = load(file_id)
    return [
        {"id": f["id"], "geometry_type": f["geometry_type"], **f["measurements"]}
        for f in result["features"]
    ]
