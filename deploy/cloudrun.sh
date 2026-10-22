#!/usr/bin/env bash
# Deploy to Google Cloud Run (scale-to-zero, pay per request).
# Prereqs: gcloud authenticated, a project with billing, and the APIs enabled:
#   gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
# Usage: PROJECT_ID=my-proj REGION=europe-west1 ./deploy/cloudrun.sh
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-industrial-power-ai}"
REPO="${REPO:-apps}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:$(git rev-parse --short HEAD)"

gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION" --project "$PROJECT_ID"

gcloud builds submit --project "$PROJECT_ID" --tag "$IMAGE" .

SECRET_FLAGS=()
# Store secrets in Secret Manager, never in env files or the image:
#   printf '%s' "$LLM_API_KEY" | gcloud secrets create llm-api-key --data-file=- --project "$PROJECT_ID"
#   printf '%s' "$ADMIN_TOKEN" | gcloud secrets create admin-token --data-file=- --project "$PROJECT_ID"
if gcloud secrets describe llm-api-key --project "$PROJECT_ID" >/dev/null 2>&1; then
  SECRET_FLAGS+=(--set-secrets "LLM_API_KEY=llm-api-key:latest")
fi
if gcloud secrets describe admin-token --project "$PROJECT_ID" >/dev/null 2>&1; then
  SECRET_FLAGS+=(--update-secrets "ADMIN_TOKEN=admin-token:latest")
fi

gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --allow-unauthenticated --memory 2Gi --cpu 1 --min-instances 0 --max-instances 2 \
  --concurrency 8 --timeout 90 \
  --set-env-vars "LLM_BASE_URL=${LLM_BASE_URL:-https://api.openai.com/v1},LLM_MODEL=${LLM_MODEL:-gpt-4o-mini},ENVIRONMENT=production" \
  "${SECRET_FLAGS[@]}"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')
echo "Deployed: $URL"
python3 deploy/verify.py "$URL"
