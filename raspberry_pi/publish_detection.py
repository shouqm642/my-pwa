#!/usr/bin/env python3
"""Capture/analyze a NABTA image and securely publish its result to the web app.

Required environment variables (load from ~/.nabta-secrets):
  ROBOFLOW_API_KEY  Private Roboflow key (never put this in the website)
  NABTA_DEVICE_TOKEN  Random upload token configured on the backend
  NABTA_API_URL  Public HTTPS URL of the deployed FastAPI service
"""
import json
import os
import sys
from pathlib import Path

import requests
from inference_sdk import InferenceHTTPClient

MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID", "insects-mytwu/1")
API_URL = os.getenv("NABTA_API_URL", "").rstrip("/")
IMAGE_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("nabta_test.jpg")


def main() -> int:
    roboflow_key = os.getenv("ROBOFLOW_API_KEY")
    device_token = os.getenv("NABTA_DEVICE_TOKEN")
    if not roboflow_key:
        print("Missing ROBOFLOW_API_KEY. Load ~/.nabta-secrets first.")
        return 2
    if not device_token:
        print("Missing NABTA_DEVICE_TOKEN. Add the backend device token to ~/.nabta-secrets.")
        return 2
    if not API_URL.startswith("https://"):
        print("Set NABTA_API_URL to your deployed HTTPS backend URL.")
        return 2
    if not IMAGE_PATH.is_file():
        print(f"Image not found: {IMAGE_PATH}")
        return 2

    print(f"NABTA AI: analyzing {IMAGE_PATH} with {MODEL_ID} ...")
    client = InferenceHTTPClient(
        api_url="https://serverless.roboflow.com",
        api_key=roboflow_key,
    )
    result = client.infer(str(IMAGE_PATH), model_id=MODEL_ID)
    print(json.dumps(result, indent=2))

    with IMAGE_PATH.open("rb") as image_file:
        response = requests.post(
            f"{API_URL}/api/detections",
            headers={"X-Device-Token": device_token},
            data={"payload": json.dumps(result)},
            files={"image": (IMAGE_PATH.name, image_file, "image/jpeg")},
            timeout=60,
        )
    response.raise_for_status()
    print("Detection securely sent to NABTA AI app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
