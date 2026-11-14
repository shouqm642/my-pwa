import json
import logging
import os
import re
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

UPLOAD_DIR = Path(os.getenv("NABTA_UPLOAD_DIR", "/tmp/nabta-uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEVICE_TOKEN = os.getenv("NABTA_DEVICE_TOKEN", "")

app = FastAPI(title="NABTA AI API", version="1.0.0")
logger = logging.getLogger("nabta.plant_assessment")
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



PLANT_HEALTH_MODEL_ID = os.getenv("PLANT_HEALTH_MODEL_ID", "leaf-disease-detection-system/2")
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")
PLANT_IMAGE_MAX_BYTES = 4 * 1024 * 1024
PLANT_ASSESSMENT_LIMIT = 5
PLANT_ASSESSMENT_WINDOW = 60 * 60
plant_assessment_requests: dict[str, list[float]] = {}


def check_plant_assessment_rate_limit(client_key: str) -> None:
    now = time.time()
    recent = [stamp for stamp in plant_assessment_requests.get(client_key, []) if now - stamp < PLANT_ASSESSMENT_WINDOW]
    if len(recent) >= PLANT_ASSESSMENT_LIMIT:
        raise HTTPException(status_code=429, detail="Plant photo limit reached. Try again in one hour.")
    recent.append(now)
    plant_assessment_requests[client_key] = recent


@app.post("/api/plant-assessment")
async def assess_plant_photo(
    request: Request,
    image: UploadFile = File(...),
    plant_name: str = Form(default=""),
) -> dict[str, Any]:
    if not ROBOFLOW_API_KEY:
        raise HTTPException(status_code=503, detail="Plant analysis is not configured. Add ROBOFLOW_API_KEY to the Render service environment.")
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Choose a JPEG, PNG, or WebP leaf photo.")
    if len(plant_name) > 80:
        raise HTTPException(status_code=400, detail="Plant name must be 80 characters or fewer.")
    client_key = request.client.host if request.client else "unknown"
    check_plant_assessment_rate_limit(client_key)
    raw = await image.read(PLANT_IMAGE_MAX_BYTES + 1)
    if not raw or len(raw) > PLANT_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Leaf photo must be no larger than 4 MB.")

    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[image.content_type]
    temp_path = None
    try:
        from inference_sdk import InferenceHTTPClient
        with tempfile.NamedTemporaryFile(prefix="nabta-plant-", suffix=suffix, delete=False) as temp_file:
            temp_file.write(raw)
            temp_path = temp_file.name
        # Match the exact Python snippet published on this Roboflow model page.
        client = InferenceHTTPClient(
            api_url="https://serverless.roboflow.com",
            api_key=ROBOFLOW_API_KEY,
        )
        model_result = client.infer(temp_path, model_id=PLANT_HEALTH_MODEL_ID)
        if not isinstance(model_result, dict):
            raise RuntimeError("Unexpected model response")
        predictions = model_result.get("predictions", [])
        if not isinstance(predictions, list):
            raise RuntimeError("Unexpected predictions format")
        resolved = model_result.get("resolved_model") if isinstance(model_result.get("resolved_model"), dict) else {}
        return {
            "status": "analysed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "plant_name": plant_name.strip(),
            "model_id": resolved.get("model_id") or PLANT_HEALTH_MODEL_ID,
            "predictions": predictions,
            "image": model_result.get("image") if isinstance(model_result.get("image"), dict) else {},
            "note": "Model screening result only; not a confirmed diagnosis."
        }
    except HTTPException:
        raise
    except Exception as exc:
        # Keep credentials out of Render logs and API responses while making the real
        # upstream failure category visible for troubleshooting.
        error_text = str(exc)
        if ROBOFLOW_API_KEY:
            error_text = error_text.replace(ROBOFLOW_API_KEY, "[REDACTED]")
        error_text = re.sub(r"(?i)(api[_-]?key[=:\\s]+)[^&\\s,]+", r"\\1[REDACTED]", error_text)
        logger.error(
            "Plant assessment failed: error_type=%s model_id=%s detail=%s",
            type(exc).__name__,
            PLANT_HEALTH_MODEL_ID,
            error_text[:800],
        )
        lower_error = error_text.lower()
        if "401" in lower_error or "403" in lower_error or "unauthorized" in lower_error:
            detail = "Roboflow rejected the API key or this model is not authorized for the account. Check the key in Render."
        elif "404" in lower_error or "not found" in lower_error:
            detail = "Roboflow could not find this model version. Check PLANT_HEALTH_MODEL_ID in Render."
        elif "429" in lower_error or "rate limit" in lower_error or "quota" in lower_error:
            detail = "Roboflow rate limit or usage quota reached. Check the Roboflow account usage."
        else:
            detail = "Roboflow inference failed. Open Render Logs for the Plant assessment error_type and detail."
        raise HTTPException(status_code=502, detail=detail)
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass

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
        "model_id": ((model_result.get("resolved_model") if isinstance(model_result.get("resolved_model"), dict) else {}) or {}).get("model_id") or model_result.get("model_id", "unknown"),
        "image_width": ((model_result.get("image") if isinstance(model_result.get("image"), dict) else {}) or {}).get("width", model_result.get("width")),
        "image_height": ((model_result.get("image") if isinstance(model_result.get("image"), dict) else {}) or {}).get("height", model_result.get("height")),
    }
    detections.insert(0, item)
    del detections[50:]
    return {"status": "received", "detection": item}
