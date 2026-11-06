# Deploying Hermes

* Host layout: code checkout in `/opt/hermes`, compose override
  `/opt/hermes/docker-compose.override.yml` pins the image tags in use.
* `deploy/deploy-overlay.sh <ref>` is the supported deploy (see header).
* Dependencies are pinned in `constraints.txt` (a freeze of the running image);
  the Dockerfile installs with `-c constraints.txt`. Unpinned rebuilds once
  crashed API startup (spaCy/numpy drift) -- do not remove it. Refresh it only
  deliberately: freeze a tested image, commit, and re-test.
* `deploy/systemd/` mirrors the host units (taxonomy triage, review resolution,
  gmail reconcile/cleanup, graph renew + alert). The host copies in
  `/etc/systemd/system` are authoritative; update both together.
* Runtime automation script: `scripts/hermes-900-daily-taxonomy-triage.py`
  (+ `hermes-taxonomy-skill-catalog.json`) is also copied to
  `/hermes-runtime/automation/taxonomy/releases/<sha>/` with a `release.json`.
