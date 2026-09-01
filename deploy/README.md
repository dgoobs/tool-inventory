# Deploying to GCP

Runs the app on a single `e2-micro` Compute Engine VM (Debian 12), which
fits inside GCP's always-free tier for a low-traffic internal tool like
this. SQLite (`inventory.db`) lives on the VM's persistent disk, so data
survives reboots and redeploys.

## One-time setup

1. **GCP project + billing** — needs a project with a billing account
   linked (Console → Billing). The always-free tier covers this VM, but
   billing still has to be on file.
2. **Pick a shop password** — this gates the whole app (one shared
   password, no individual accounts).
3. Build the startup script and create the VM:

   ```bash
   ./deploy/build.sh
   SHOP_PASSWORD='choose-a-password' ./deploy/gcp-deploy.sh
   ```

   This creates a firewall rule (port 8080), a static external IP, and
   the VM itself. The VM installs Python, the app, and starts it via
   systemd automatically on first boot — takes ~1-2 minutes after the
   instance is created. The command prints the URL
   (`http://<static-ip>:8080`) at the end.

## Making code changes later

Edit the app locally as usual, then push the update:

```bash
./deploy/redeploy.sh
```

This repackages the current code, uploads it to the VM, and reboots it.
`inventory.db` and the session signing key are left alone — only the
application code changes.

## Changing the shop password

```bash
gcloud compute instances add-metadata tool-inventory \
  --zone=us-central1-a --metadata=shop-password='new-password'
gcloud compute instances reset tool-inventory --zone=us-central1-a
```

## Useful commands

```bash
# Tail the app's logs
gcloud compute ssh tool-inventory --zone=us-central1-a \
  --command='sudo journalctl -u toolinventory -f'

# SSH in directly
gcloud compute ssh tool-inventory --zone=us-central1-a

# Back up the database to your machine
gcloud compute scp tool-inventory:/opt/toolinventory/inventory.db . \
  --zone=us-central1-a

# Tear everything down
gcloud compute instances delete tool-inventory --zone=us-central1-a
gcloud compute addresses delete tool-inventory-ip --region=us-central1
gcloud compute firewall-rules delete allow-tool-inventory
```

## Notes / future improvements

- **HTTP only, no TLS.** Fine for an internal tool, but credentials and
  data travel unencrypted. Adding a domain name + free TLS cert (e.g. via
  Caddy) is a natural next step if this becomes more than an internal
  tool.
- **No automatic backups.** The `gcloud compute scp` command above pulls
  a copy of `inventory.db`; consider running it on a schedule.
- **Firewall is open to the whole internet** on port 8080. The shop
  password protects it, but you can further restrict
  `--source-ranges` on the firewall rule to known IPs if you want to
  narrow that.
