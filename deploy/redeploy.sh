#!/usr/bin/env bash
# Pushes code changes to the already-created VM: rebuilds the startup
# script with the current app code, uploads it as instance metadata, then
# reboots the VM so it re-runs and picks up the change.
# inventory.db and the login session key are untouched.
set -euo pipefail
cd "$(dirname "$0")/.."

ZONE="us-central1-a"
INSTANCE_NAME="tool-inventory"

./deploy/build.sh

gcloud compute instances add-metadata "$INSTANCE_NAME" \
  --zone="$ZONE" \
  --metadata-from-file=startup-script=deploy/startup-script.sh

gcloud compute instances reset "$INSTANCE_NAME" --zone="$ZONE"

echo "Redeployed. Give it ~1-2 minutes to come back up."
