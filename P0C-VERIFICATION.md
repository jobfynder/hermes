# Hermes P0-C — implementation ready; rollout gated

Date: 2026-10-14. Base: P0-B `21adc30537d86b2b2b4478e78299a88c3995e04e`.

## Read-only discovery

Read `P0B-VERIFICATION.md` first. No repository `AGENTS.md` was found in the workspace or checked parent locations. SSH alias `intel` confirms production source remains at the P0-B commit and `hermes-api:p0b-21adc30` is running. Production tracked files were not changed by this task; pre-existing untracked environment backups and deployment files were left alone.

`gcloud` is unavailable on the host, and `/root/.config/gcloud` was not present. Production `.env` has Gmail OAuth client/secret/refresh-token and polling settings, but no Pub/Sub topic/subscription or push identity settings. A restricted scan of `.env*` files for non-secret project/topic/subscription/audience/service-account keys found only the empty topic example. Repository deployment/docs/scripts search did not establish subscription configuration. OAuth client credentials do not establish a Pub/Sub push service-account identity.

**Actual Google project, subscription, push endpoint, effective audience and authorized service account remain unconfirmed.** This does not establish that no subscription exists. No Google resource APIs were called, since no confirmed project/subscription or authorized Cloud inspection context was available. No identities were guessed and no credentials were printed.

## Reviewable implementation

`app/security/google_push.py` provides an independent FastAPI dependency factory taking explicit trusted `PushIdentity` configuration. It uses `google.oauth2.id_token.verify_oauth2_token` for Google signature, expiry, audience and issuer verification; then requires exact scalar audience, one of Google's two issuers, exact configured service-account email, boolean `email_verified=True`, nonempty subject and finite unexpired numeric expiry. Duplicate/missing/malformed Authorization headers, failed verification and certificate transport errors reject with generic HTTP 401. Certificate requests have a five-second timeout. A synchronous dependency keeps verification off the async event loop. Google transport uses its standard HTTPS trust configuration.

No dependency is attached to the production Gmail push route yet. Its existing pending P0-C route-policy classification and all bearer/RBAC code remain unchanged. The new verifier has no permissive/disabled mode. The Gmail route remains publicly accessible under the existing P0-B exception until a separately reviewed activation change; this work does not close that exposure.

Dependency: `google-auth[requests]>=2.62,<3`, tested with 2.62.0. Certificate caching is not implemented; evaluate delivery volume and cache/retry needs before activation. No API image was built or deployed.

## Validation

Run: `python -m unittest discover -s tests -p test_google_push.py -v`.

Eight independent unittest methods cover missing/malformed/duplicate credentials, invalid and expired tokens, wrong audience/issuer/service account, missing claims, unverified or string-valued email verification, invalid expiry values, missing trusted configuration, verification transport failures, and successful handler entry. Rejected requests cannot enter the test handler, even with malformed request bodies. Real google-auth RSA verification uses generated synthetic keys and mocked certificate transport to verify correct signatures and reject wrong signatures, expired tokens, future issuance, wrong audience and wrong issuer. No real Google tokens or external services are used. The CI workflow includes this suite.

Existing application/RBAC routes were not modified. Full application regression tests were not rerun in this isolated minimal dependency environment. Compile and diff checks accompany the independent suite.

## Precise rollout prerequisite

1. Obtain an authorized read-only description of the actual subscription: project ID/number, full subscription resource name, topic, `pushConfig.pushEndpoint`, `pushConfig.oidcToken.serviceAccountEmail`, and `pushConfig.oidcToken.audience`. If the audience field is omitted, Google's documented effective audience is the configured push endpoint URL; confirm this rather than using an incoming Host header.
2. Confirm the intended service-account identity and that the Pub/Sub service agent can mint its OIDC token. Missing `oidcToken` means authenticated delivery must be configured in a separately authorized rollout before enforcement. Do not derive the push identity from the Gmail OAuth client or Pub/Sub service agent email.
3. Independently validate those exact settings and authorized delivery before attaching `Depends(require_google_push(confirmed_identity))` to `/providers/gmail/push`. Validate rejection before body reads/fetch/intake with application integration tests; update the route-policy inventory and its pending assertion only with activation. Keep Hermes bearer credentials separate.
4. Prepare an API-only deployment/rollback preserving P0-A, existing publication/topology, worker containers and polling. Do not activate enforcement until actual authenticated delivery and independent tests support it. Preserve all P0-B exceptions and Twenty's existing disabled synchronization gate.

No production mutation, restart, firewall change, mailbox mutation, replay, Core creation, live model test, parser/schema/matching change or credential rotation occurred. Existing P0-B rollback records remain `/root/hermes-p0b-20261013`.

Reference: [Google authenticated push verification](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions), [OIDC audience default](https://cloud.google.com/php/docs/reference/cloud-pubsub/latest/V1.PushConfig.OidcToken).
