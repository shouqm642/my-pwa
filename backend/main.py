import json
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

UPLOAD_DIR = Path(os.getenv("NABTA_UPLOAD_DIR", "/var/data/nabta-uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEVICE_TOKEN = os.getenv("NABTA_DEVICE_TOKEN", "")

app = FastAPI(title="NABTA AI API", version="1.0.0")
allowed_origins = [
    item.strip()
    for item in os.getenv(
        "ALLOWED_ORIGINS",
        "https://shouqm642.github.io,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Device-Token"],
)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# In-memory metadata is suitable for a prototype. Use a database for durable history.
detections: list[dict[str, Any]] = []


def require_device_token(value: str | None) -> None:
    if not DEVICE_TOKEN:
        raise HTTPException(status_code=503, detail="NABTA_DEVICE_TOKEN is not configured")
    if not value or not secrets.compare_digest(value, DEVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid device token")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "NABTA AI"}


# Read-only dashboard endpoints are public. Never include private keys or personal data here.
@app.get("/api/latest")
def latest() -> dict[str, Any]:
    return {"detection": detections[0] if detections else None}


@app.get("/api/history")
def history() -> dict[str, Any]:
    return {"detections": detections[:50]}


@app.post("/api/detections")
async def create_detection(
    request: Request,
    payload: str = Form(...),
    image: UploadFile = File(...),
    x_device_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_device_token(x_device_token)
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, or WebP images are accepted")
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is empty or exceeds 8 MB")
    try:
        model_result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="payload must be valid JSON") from exc
    predictions = model_result.get("predictions", [])
    if not isinstance(predictions, list):
        raise HTTPException(status_code=400, detail="predictions must be a list")

    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[image.content_type]
    filename = f"{int(time.time())}-{uuid.uuid4().hex[:10]}{suffix}"
    (UPLOAD_DIR / filename).write_bytes(raw)
    public_base = os.getenv("PUBLIC_BASE_URL", str(request.base_url).rstrip("/")).rstrip("/")
    item = {
        "id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "predictions": predictions,
        "image_url": f"{public_base}/uploads/{filename}",
        "model_id": model_result.get("model_id", "insects-mytwu/1"),
        "image_width": (model_result.get("image") or {}).get("width"),
        "image_height": (model_result.get("image") or {}).get("height"),
    }
    detections.insert(0, item)
    del detections[50:]
    return {"status": "received", "detection": item}
