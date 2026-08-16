#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
DATA_DIR="${REPO_ROOT}/data"
JSON_DIR="${DATA_DIR}/json"
REPORTS_DIR="${DATA_DIR}/reports"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"
BACKEND_ENV="${REPO_ROOT}/backend/.env"

# Replace each placeholder with a public Google Drive share URL. The value after
# the | is the path where the backend expects that JSON file.
JSON_DOWNLOADS=(
  "https://drive.google.com/file/d/1SuT5b1easepuf7U-ao5QZn0AsczCA6tz/view?usp=sharing|client_data.json"
  "https://drive.google.com/file/d/152aktG-eDf3z2U01UFm58MR-fYCTXUyi/view?usp=sharing|mock_clients.json"
  "https://drive.google.com/file/d/1wm9wXK8fxI84VsS_f9vZpJvgG2bHnPv3/view?usp=sharing|json/calculation_details.json"
  "https://drive.google.com/file/d/1UpcT-YtCz9rYVNZBUV1At_wYnGYeDN7-/view?usp=sharing|json/client_baseline.json"
  "https://drive.google.com/file/d/1EohJiVohpxqxXCubbBCl0ul8CwErwyvJ/view?usp=sharing|json/client_timing_intelligence.json"
  "https://drive.google.com/file/d/15QxVIM1TvlBPFobJbcrz46JRW2At3pvT/view?usp=sharing|json/current_external_data.json"
  "https://drive.google.com/file/d/18gJT0D9K7d-IDCFO9PZi2aDxlIeHpIS2/view?usp=sharing|json/current_sens_data.json"
  "https://drive.google.com/file/d/1YR74DrVE4eK_VPU22ZR5GyGmFYO0DRN7/view?usp=sharing|json/pipeline_status.json"
  "https://drive.google.com/file/d/1BlNlz-o026jj__2QNWTGkFr1TR_0mqb1/view?usp=sharing|json/processed_documents.json"
  "https://drive.google.com/file/d/1gnqpr07s8v0Pa_XML3yr5qVWgMP4GOVD/view?usp=sharing|json/relationship_managers.json"
  "https://drive.google.com/file/d/1uIul6yxkla-Bg7NNSNmrRdgt4LKXV4ND/view?usp=sharing|json/report_manifest.json"
  "https://drive.google.com/file/d/1ABoCEtvL8nlyG5fNVvYkAQFwUcsQ7uTm/view?usp=sharing|json/wallet_sizes.json"
)

# These filenames must match json/report_manifest.json. Replace the three URL
# placeholders with the public Google Drive links after uploading the reports.
REPORT_DOWNLOADS=(
  "https://drive.google.com/file/d/1x5rHcVpyLIqvy431nO-bhZ50mUMSiotU/view?usp=sharing|reports/E02-Glencore-briefing.html"
  "https://drive.google.com/file/d/1xmVWIFN2LmhDicESJZseC0baYtrius0v/view?usp=sharing|reports/E01-BHP_Group-briefing.html"
  "https://drive.google.com/file/d/1FJMAYiXhr7Wiups017oJIazC_7s7gK0W/view?usp=sharing|reports/E10-Bid_Corporation-briefing.html"
)

log() {
  printf '[run_local] %s\n' "$*"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  log "Stopping local servers..."
  [[ -n "${FRONTEND_PID:-}" ]] && kill "${FRONTEND_PID}" 2>/dev/null || true
  [[ -n "${BACKEND_PID:-}" ]] && kill "${BACKEND_PID}" 2>/dev/null || true
  wait "${FRONTEND_PID:-}" "${BACKEND_PID:-}" 2>/dev/null || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

command -v python3 >/dev/null 2>&1 || {
  log "python3 is required but was not found."
  exit 1
}
command -v npm >/dev/null 2>&1 || {
  log "npm is required but was not found."
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  log "curl is required but was not found."
  exit 1
}

log "Copying ${ENV_EXAMPLE} to ${BACKEND_ENV}..."
cp -- "${ENV_EXAMPLE}" "${BACKEND_ENV}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  log "Creating Python virtual environment at ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
fi

# Activating makes the environment available to this script and child processes.
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
  log "Installing backend dependencies..."
  python -m pip install -r "${REPO_ROOT}/backend/requirements.txt"
fi

mkdir -p "${JSON_DIR}" "${REPORTS_DIR}"

if [[ "${SKIP_DOWNLOADS:-0}" != "1" ]]; then
  for item in "${JSON_DOWNLOADS[@]}"; do
    url="${item%%|*}"
    relative_path="${item#*|}"
    destination="${DATA_DIR}/${relative_path}"

    if [[ "${url}" == PASTE_*_HERE ]]; then
      if [[ -s "${destination}" ]]; then
        log "No URL set for ${relative_path}; keeping the existing file."
        continue
      fi
      log "Missing Google Drive URL for ${relative_path}. Edit ${SCRIPT_DIR}/run_local.sh."
      exit 1
    fi

    mkdir -p "$(dirname -- "${destination}")"
    log "Downloading ${relative_path}..."
    python -m gdown "${url}" --output "${destination}"

    python -m json.tool "${destination}" >/dev/null || {
      log "Downloaded file is not valid JSON: ${destination}"
      exit 1
    }
  done

  for item in "${REPORT_DOWNLOADS[@]}"; do
    url="${item%%|*}"
    relative_path="${item#*|}"
    destination="${DATA_DIR}/${relative_path}"

    if [[ "${url}" == PASTE_*_HERE ]]; then
      if [[ -s "${destination}" ]]; then
        log "No URL set for ${relative_path}; keeping the existing report."
        continue
      fi
      log "Missing Google Drive URL for ${relative_path}. Edit ${SCRIPT_DIR}/run_local.sh."
      exit 1
    fi

    log "Downloading ${relative_path}..."
    python -m gdown "${url}" --output "${destination}"

    if [[ ! -s "${destination}" ]]; then
      log "Downloaded report is empty: ${destination}"
      exit 1
    fi
  done
else
  log "Skipping Google Drive downloads (SKIP_DOWNLOADS=1)."
fi

if [[ ! -s "${DATA_DIR}/client_data.json" ]]; then
  log "${DATA_DIR}/client_data.json is required for the API."
  exit 1
fi

if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
  log "Installing frontend dependencies..."
  npm --prefix "${REPO_ROOT}/frontend" ci
fi

export APP_DATA_DIR="${DATA_DIR}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:5173}"
export PIPELINE_SCHEDULER_ENABLED="${PIPELINE_SCHEDULER_ENABLED:-false}"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://localhost:4000/api}"

log "Starting backend at http://localhost:4000..."
python -m uvicorn backend.app:app --app-dir "${REPO_ROOT}" --host 127.0.0.1 --port 4000 &
BACKEND_PID=$!

for attempt in {1..30}; do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    wait "${BACKEND_PID}"
  fi
  if curl --fail --silent "http://localhost:4000/health" >/dev/null; then
    break
  fi
  if [[ "${attempt}" -eq 30 ]]; then
    log "Backend did not become healthy within 30 seconds."
    exit 1
  fi
  sleep 1
done

log "Starting frontend at http://localhost:5173..."
npm --prefix "${REPO_ROOT}/frontend" run dev -- --host 127.0.0.1 &
FRONTEND_PID=$!

log "Ready: frontend http://localhost:5173 | API docs http://localhost:4000/docs"
log "Press Ctrl+C to stop both servers."

wait -n "${BACKEND_PID}" "${FRONTEND_PID}"
