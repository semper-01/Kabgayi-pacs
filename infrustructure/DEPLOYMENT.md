# Production deployment

This package is separate from the development Compose stack. It has not been
deployed to the hospital server. Do not run these steps there until the host,
DNS name, network access, and maintenance window have been approved.

## Important network limitation

The current gateway listens on plain HTTP port 80. The generated environment
sets `VIEWER_GRANT_COOKIE_SECURE=false` so the viewer grant cookie works over
that HTTP connection. This is not suitable for an untrusted or Internet-facing
network: obtain an approved TLS termination design before wider exposure.
Port 4242 is also published for DICOM traffic and must be restricted by the
network owner to approved modality/client networks. Orthanc's management port
8042 is bound to loopback only.

## Build and transfer images

Build on a Linux/AMD64-compatible Docker builder, using the checked-out source
revision that will be deployed:

```powershell
docker build --platform linux/amd64 --tag kabgayi-pacs-frontend:production --file frontend/Dockerfile frontend
docker build --platform linux/amd64 --tag kabgayi-pacs-backend:production --file backend/Dockerfile backend
```

The OHIF image is the previously verified `kabgayi-ohif:3.13.12-hotfix`.
Confirm it exists locally; do not rebuild or retag the known-good rollback
image. Export the three application images and record the archive checksum:

```powershell
docker image inspect kabgayi-pacs-frontend:production kabgayi-pacs-backend:production kabgayi-ohif:3.13.12-hotfix
docker image save --output infrustructure/pacs-deployment-images.tar kabgayi-pacs-frontend:production kabgayi-pacs-backend:production kabgayi-ohif:3.13.12-hotfix
tar -czf infrustructure/pacs-deployment-config.tar.gz -C infrustructure docker-compose.production.yml nginx/nginx.production.conf.template ohif/app-config.js scripts/create-production-env.py .env.production.example DEPLOYMENT.md
Get-FileHash .\infrustructure\pacs-deployment-images.tar -Algorithm SHA256
Get-FileHash .\infrustructure\pacs-deployment-config.tar.gz -Algorithm SHA256
```

Transfer both archives to the approved Ubuntu/AMD64 host using the hospital's
authorized transfer method. The config archive contains only the production
Compose file and its required templates/scripts; it excludes the pre-deployment
backup and OHIF rollback bundle. Do not include `.env.production` or other
credentials. Verify both SHA256 checksums after transfer. The pinned Nginx,
PostgreSQL, and Orthanc images are pulled by digest from their registries;
pre-load those images too if the host has no registry access.

## Prepare the host

1. Confirm this is the intended host and that the required ports and storage
   paths are approved. Check `/srv/pacs/postgres` and `/srv/pacs/orthanc` before
   creating anything; do not reuse, move, or overwrite existing PACS data.
2. Extract the config archive into a new, empty deployment directory and load
   the transferred images. Confirm the expected tags:

   ```sh
   tar -xzf pacs-deployment-config.tar.gz
   docker image load --input pacs-deployment-images.tar
   docker image inspect kabgayi-pacs-frontend:production kabgayi-pacs-backend:production kabgayi-ohif:3.13.12-hotfix
   ```

3. Generate credentials on the server. Supply only ICT-approved hostnames/IPs;
   never use `*`. The generator refuses to overwrite an existing environment
   file and does not print secrets:

   ```sh
   cd infrustructure
   python3 scripts/create-production-env.py --allowed-hosts approved-pacs-hostname,approved-private-ip
   chmod 600 .env.production
   ```

   Review non-secret settings in `.env.production`. Do not copy secrets into
   shell history, chat, source control, or deployment logs. If a generated
   environment file already exists, stop and preserve it; do not regenerate
   credentials over an active deployment.

4. Validate the Compose model before starting services:

   ```sh
   docker compose --env-file .env.production --file docker-compose.production.yml config --quiet
   ```

5. Back up any existing application database and DICOM data using the
   institution's approved, consistency-safe procedures. This deployment
   definition uses `/srv/pacs/postgres` and `/srv/pacs/orthanc`; it must not be
   pointed at existing data without an explicit migration and rollback plan.

## Initialize and start

Run these commands from `infrustructure` on the approved host. Registry access
is required for the pinned infrastructure images. No Django or PostgreSQL
ports are published to the host.

```sh
docker compose --env-file .env.production --file docker-compose.production.yml pull nginx postgres orthanc
docker compose --env-file .env.production --file docker-compose.production.yml up -d postgres orthanc
docker compose --env-file .env.production --file docker-compose.production.yml run --rm django python manage.py migrate --noinput
docker compose --env-file .env.production --file docker-compose.production.yml run --rm django python manage.py collectstatic --noinput
docker compose --env-file .env.production --file docker-compose.production.yml up -d
docker compose --env-file .env.production --file docker-compose.production.yml ps
```

Create the first Django superuser interactively, then set the PACS administrator
account type (the model's default for a superuser is `staff`):

```sh
docker compose --env-file .env.production --file docker-compose.production.yml run --rm django python manage.py createsuperuser
docker compose --env-file .env.production --file docker-compose.production.yml run --rm django python manage.py shell -c "from core.models import User; User.objects.filter(username='YOUR_USERNAME').update(account_type='administrator')"
```

Replace `YOUR_USERNAME` with the account just created. Use a unique strong
password and verify administrator access over the approved network.

## Verify before use

- Check `docker compose ... ps` and `docker inspect` to confirm all services are
  healthy and the frontend, backend, and OHIF containers use the expected image
  IDs.
- `curl -fsS http://127.0.0.1/api/health/` should return the Django health
  response. Check `docker compose ... logs --tail=100 nginx django orthanc`.
- Verify that `/viewer` and `/dicom-web/` cannot be used without the normal
  PACS sign-in/study grant flow. Open a study from the authorized PACS
  application and confirm its DICOMweb requests succeed only while that grant
  is valid.
- Test one Siemens DX and one Siemens CT study through the authorized UI,
  confirming image display, window/level behavior, and no console/network
  errors. Do not use unrestricted DICOM queries for this check.
- Confirm port 8042 is reachable only through loopback/approved administration
  access and that port 4242 is reachable only from authorized DICOM peers.
- Do not declare the deployment complete based on container health alone.

## Backup, update, and rollback

Before each update, record the running image IDs and tag the currently deployed
frontend/backend images with unique rollback tags. Preserve the running OHIF
known-good image/container and its rollback artifacts until the replacement
has passed the DX/CT checks above.

For an application database backup, use the approved storage location and
restrict file permissions:

```sh
umask 077
docker compose --env-file .env.production --file docker-compose.production.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > /approved/backup/path/pacs-postgres.sql
```

Back up Orthanc data with a consistency-safe procedure, including a planned
write pause if required. Do not copy a live Orthanc storage directory as if it
were a consistent backup.

For an update, build and verify the replacement images off-host, transfer and
load them, validate Compose, run reviewed database migrations and static
collection, then recreate the application services. Keep the prior image IDs,
rollback tags, database backup, and DICOM backup until acceptance is complete.
To roll back application images, restore the previous frontend/backend tags
under the image names used by Compose and recreate only the affected
application services. Restore database or DICOM data only when required by the
change and only from the verified backup; never delete existing data or
rollback artifacts as part of routine cleanup.
