#!/usr/bin/env bash
set -euo pipefail

# Usage: bash auto_capture_publish.sh [number_of_photos] [seconds_between_photos]
COUNT="${1:-5}"
INTERVAL="${2:-60}"

if ! [[ "$COUNT" =~ ^[1-9][0-9]*$ ]]; then
  echo "Number of photos must be a positive integer."
  exit 2
fi
if ! [[ "$INTERVAL" =~ ^[1-9][0-9]*$ ]]; then
  echo "Interval must be a positive integer in seconds."
  exit 2
fi

PROJECT_DIR="$HOME/NABTA_AI"
IMAGE_PATH="$PROJECT_DIR/nabta_auto_latest.jpg"

cd "$PROJECT_DIR"

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Python virtual environment not found at $PROJECT_DIR/.venv"
  exit 2
fi
if [[ ! -f "$PROJECT_DIR/publish_detection.py" ]]; then
  echo "publish_detection.py not found. Download it from the NABTA repository first."
  exit 2
fi

echo "NABTA AI automatic capture: $COUNT photos, $INTERVAL seconds apart."
echo "Press Ctrl+C at any time to stop."

for ((i=1; i<=COUNT; i++)); do
  echo
  echo "===== Capture $i of $COUNT ====="
  rpicam-still -n -t 1500 -o "$IMAGE_PATH"
  "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/publish_detection.py" "$IMAGE_PATH"

  if (( i < COUNT )); then
    echo "Waiting $INTERVAL seconds before the next capture..."
    sleep "$INTERVAL"
  fi
done

echo
echo "NABTA AI automatic capture test completed."
