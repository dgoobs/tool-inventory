#!/usr/bin/env bash
# One-time setup: creates the firewall rule, a static IP, and the VM.
# Requires: gcloud authenticated, project set, billing enabled.
# Requires deploy/startup-script.sh to exist (run deploy/build.sh first).
#
# Usage:
#   SHOP_PASSWORD='choose-a-password' ./deploy/gcp-deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="inventory-tracker-507320"
REGION="us-central1"
ZONE="us-central1-a"
INSTANCE_NAME="tool-inventory"
FIREWALL_NAME="allow-tool-inventory"
IP_NAME="tool-inventory-ip"

: "${SHOP_PASSWORD:?Set SHOP_PASSWORD, e.g. SHOP_PASSWORD='yourpassword' ./deploy/gcp-deploy.sh}"

gcloud config set project "$PROJECT_ID"
gcloud services enable compute.googleapis.com

if ! gcloud compute firewall-rules describe "$FIREWALL_NAME" >/dev/null 2>&1; then
  gcloud compute firewall-rules create "$FIREWALL_NAME" \
    --allow=tcp:8080 \
    --target-tags=tool-inventory \
    --direction=INGRESS \
    --source-ranges=0.0.0.0/0
fi

if ! gcloud compute addresses describe "$IP_NAME" --region="$REGION" >/dev/null 2>&1; then
  gcloud compute addresses create "$IP_NAME" --region="$REGION"
fi
STATIC_IP="$(gcloud compute addresses describe "$IP_NAME" --region="$REGION" --format='get(address)')"

gcloud compute instances create "$INSTANCE_NAME" \
  --zone="$ZONE" \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --tags=tool-inventory \
  --address="$STATIC_IP" \
  --metadata-from-file=startup-script=deploy/startup-script.sh \
  --metadata=shop-password="$SHOP_PASSWORD"

echo ""
echo "Created. The app takes ~1-2 minutes to install and start after the VM boots."
echo "It will be live at: http://$STATIC_IP:8080"
