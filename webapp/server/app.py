"""FastAPI application exposing the translation workflow over HTTP."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .service import TranslationService

DATA_ROOT = Path(__file__).resolve().parents[2] / "Data"
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"

app = FastAPI(title="xTranslator Browser Bridge")
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
service = TranslationService(DATA_ROOT)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_file = STATIC_ROOT / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=500, detail="Missing index.html")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.post("/api/extract")
async def extract(game: str = Form(...), esp: UploadFile = File(...)) -> Response:
    esp_bytes = await esp.read()
    try:
        workbook_bytes, _ = service.extract(esp_bytes, game)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = Path(esp.filename or "translations").stem + "_translations.xlsx"
    headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
    return Response(content=workbook_bytes, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@app.post("/api/apply")
async def apply(game: str = Form(...), esp: UploadFile = File(...), workbook: UploadFile = File(...)) -> Response:
    esp_bytes = await esp.read()
    workbook_bytes = await workbook.read()
    try:
        rebuilt = service.apply(esp_bytes, workbook_bytes, game)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = Path(esp.filename or "translation").stem + "_translated.esp"
    headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
    return Response(content=rebuilt, media_type="application/octet-stream", headers=headers)


@app.get("/api/games")
def list_games() -> list[str]:
    if not DATA_ROOT.exists():
        return []
    return sorted([p.name for p in DATA_ROOT.iterdir() if p.is_dir()])
