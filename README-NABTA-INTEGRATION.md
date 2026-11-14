# NABTA AI — Raspberry Pi to Web App integration

This integration adds a small FastAPI service between the Raspberry Pi and the GitHub Pages PWA.

## Architecture

Raspberry Pi camera → Roboflow inference → authenticated HTTPS upload → FastAPI → public read-only dashboard → GitHub Pages app.

**Security:** Keep the Roboflow private key and the device upload token only on the Raspberry Pi/backend environment. Never add either key to `index.html`, GitHub Pages, screenshots, or a public repository.

## 1. Deploy the backend

The repository includes `render.yaml`, `backend/Dockerfile`, and `backend/requirements.txt` for a Render web service.

1. In Render, create a new Blueprint from this GitHub repository and select the branch `main`.
2. Render reads `render.yaml` and generates a private `NABTA_DEVICE_TOKEN`. Copy this value from the service environment after deployment; do not place it in the website.
3. After deployment, note the HTTPS service URL, for example `https://nabta-ai-api.onrender.com`.
4. Check `https://YOUR-SERVICE/api/health`; it should return `{"status":"ok","service":"NABTA AI"}`.

The included blueprint uses Render's free web-service plan for a no-cost prototype. Free services can sleep when idle, and their local files are ephemeral. This means the latest detection list and uploaded image files can disappear when the service restarts or spins down. For persistent image/history storage, switch to a paid service with a persistent disk or add a database and object storage. Review Render's current pricing before choosing a paid option.

The dashboard's GET endpoints (`/api/latest` and `/api/history`) are read-only and public so GitHub Pages can retrieve results without putting a secret in browser code. Uploads to `POST /api/detections` require `X-Device-Token`. Only publish images that are safe to make public. For private image history, add user authentication and private object storage before using this with personal data.

## 2. Add device settings on Raspberry Pi

On the Pi, open the private environment file (do not upload it to GitHub):

```bash
nano /home/nabta/.nabta-secrets
```

Keep your existing Roboflow line and add these lines, using the backend URL and generated device token from Render:

```bash
export NABTA_DEVICE_TOKEN='PASTE_THE_BACKEND_DEVICE_TOKEN_HERE'
export NABTA_API_URL='https://YOUR-SERVICE.onrender.com'
```

Save with Ctrl+O, Enter, Ctrl+X, then run:

```bash
chmod 600 /home/nabta/.nabta-secrets
source /home/nabta/.nabta-secrets
```

Install requests in the existing virtual environment if needed:

```bash
cd ~/NABTA_AI
source .venv/bin/activate
python3 -m pip install requests inference-sdk
```

On the Raspberry Pi, download the publisher script directly from the merged `main` branch into `~/NABTA_AI/publish_detection.py`, then run:

```bash
python3 publish_detection.py ladybug.jpg
```

The script sends the image and the Roboflow prediction JSON to the backend over HTTPS. It does not send either secret to the browser.

## 3. Connect the app

After the new GitHub Pages version is deployed, open the app, find **NABTA AI · Cloud Detection**, paste the backend HTTPS URL, and press **Connect**. The page polls `/api/latest` every 15 seconds.

The original Bluetooth controls remain available and unchanged.

## API

- `GET /api/health` — health check
- `GET /api/latest` — latest public detection and image URL
- `GET /api/history` — up to 50 recent detections (in-memory metadata)
- `POST /api/detections` — authenticated multipart upload with fields `payload` (Roboflow JSON) and `image` (JPEG/PNG/WebP)

## Prototype limitations

- The current model ID defaults to `insects-mytwu/1`; it only recognizes labels it was trained for. A high confidence score is not proof that the insect species is correct.
- The web dashboard displays results produced by the Raspberry Pi script; it does not yet trigger the robot to move or capture automatically.
- The Pi still needs an internet-connected network to call Roboflow and the backend.


## 4. Run a limited automatic camera test

For a short automatic test, download `raspberry_pi/auto_capture_publish.sh` into `~/NABTA_AI` on the Pi, then run:

```bash
bash auto_capture_publish.sh
```

By default it captures and uploads 5 photos, 60 seconds apart. You can choose a different count and interval in seconds, for example `bash auto_capture_publish.sh 3 90`. Press `Ctrl+C` to stop early. Keep the insect in view and use good lighting. This test does not move the robot.

## 5. Model comparison and confidence review

The PWA reads up to 10 recent test submissions from `GET /api/history` and displays the model ID recorded by Roboflow. To compare candidate models fairly, upload the same test image separately with each model ID set via `ROBOFLOW_MODEL_ID` on the Raspberry Pi. This is a manual comparison workflow; the system does not automatically fan out one image to multiple models or incur extra inference charges.

The dashboard treats confidence below 60% (or missing confidence) as **Needs verification**. Scores at or above 60% are still shown as **Model estimate — verify species**; a confidence score is not proof that the species label is correct. Low-confidence outputs are not sent as pest alerts and do not generate treatment suggestions.

## 6. Insect risk and treatment advisor

The PWA includes a bilingual, rule-based IPM advisor. It combines the latest model label (when it matches a supported pest), plant group/name selected by the user, and observed infestation extent to show a preliminary plant-risk level and practical control steps. Beneficial/neutral insects (for example lady beetles, dragonflies and honeybees) are not treated as plant pests. Low-confidence model results are flagged for verification and should not drive pesticide selection.

The advisor is general decision support, not a species- or crop-specific diagnosis. Its chemical-control guidance is intentionally non-prescriptive: it does not provide a dose or product recommendation. Use only a pesticide currently registered in the UAE whose label explicitly covers the exact crop/site and target pest; follow PPE, re-entry and pre-harvest intervals. This is especially important for food crops and pollinators.

Guidance sources shown in the app include UC IPM aphid, whitefly, spider-mite, mealybug and less-toxic-insecticide guidance, plus the UAE Ministry of Climate Change and Environment website.

## 8. Plant leaf photo screening

The PWA includes a leaf photo screening card. It posts a JPEG, PNG or WebP image (maximum 4 MB) to `POST /api/plant-assessment`. The backend calls the Roboflow Inference SDK with `PLANT_HEALTH_MODEL_ID` (default `leaf-disease-detection-system/2`). The private Roboflow key stays in the Render environment and is never sent to the browser.

**Required Render setup:** add `ROBOFLOW_API_KEY` as a secret environment variable on the `nabta-ai-api` service. The Blueprint declares this value as `sync: false`; it must be supplied in Render's Environment settings. Do not put the key in GitHub, the PWA, screenshots or chat. Rotate any key previously exposed in a screenshot before reuse. The endpoint allows five photo checks per IP per hour in this in-memory prototype.

The selected model reports 37 classes for selected crops (including tomato, potato, apple, grape, pepper and corn); it does not cover every plant species. No detection is not proof of health, and a "healthy" class does not rule out all conditions. The app describes outputs as preliminary screening only. Chemical or fungicide choices must be independently confirmed against current UAE registration and the exact product label.
