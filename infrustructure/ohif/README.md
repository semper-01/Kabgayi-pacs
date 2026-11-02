# Reproducible OHIF hotfix build

The deployed OHIF release was identified from the running container's Compose image digest: it matches the AMD64 manifest for `ohif/app:v3.13.12`. That release maps to OHIF commit `e844561fa487dc8f572643b6aa6584fd806e60d3`.

The build clones that exact commit, verifies the commit and package versions, applies the two pinned `@cornerstonejs` dependency patches, builds with the release's `pnpm-lock.yaml`, runs focused regressions against the installed dependencies and generated production bundle, and packages the result using the digest-pinned v3.13.12 runtime image. The source checkout remains build-time input; no second repository or vendored OHIF tree is required.

The dependency patches target the exact versions in OHIF v3.13.12:

- `@cornerstonejs/dicom-image-loader@5.6.8`: retain the entire scalar VOI LUT Function value (for example `LINEAR`), while preserving array handling.
- `@cornerstonejs/metadata@5.6.8`: only calculate an ERMF ratio from finite, positive source-to-patient distance and a finite source-to-detector distance greater than it.

Build and run the focused tests without replacing the active container:

```powershell
docker compose -f .\infrustructure\docker-compose.yml build ohif
```

The Compose service image is tagged `kabgayi-ohif:3.13.12-hotfix`. A build alone leaves the currently running `ohif` container untouched. Before promoting a built image, validate it alongside the live service with the Siemens DX and CT regression studies and retain the current container and rollback bundle until that validation succeeds.

Before promotion, snapshot the live hotfixed container to a local rollback image and keep the existing rollback bundle:

```powershell
docker commit ohif kabgayi-ohif:known-good-live-YYYYMMDD
```

After validation, deploy the already-built and tested image with the existing Compose workflow. `--no-build` ensures this deploys the exact candidate image that was validated:

```powershell
docker compose -f .\infrustructure\docker-compose.yml up -d --no-deps --no-build ohif
```

To roll back, tag the saved image as `kabgayi-ohif:3.13.12-hotfix` and run the same Compose command. The Compose service continues to mount the existing `app-config.js`; do not use a mutable `latest` tag as the rollback identity.
