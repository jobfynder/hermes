# Nvoids Gmail intake

Use a dedicated Google account for the nvoids collector. Copy the sheet linked
from `https://jobs.nvoids.com/groups.html`, authorize it once, and add a
time-driven Apps Script trigger for its fetch function. The Apps Script runs in
Google's cloud; no browser, Outlook process, Windows patch, or workstation must
remain online.

Hermes should read this Gmail mailbox directly. Configure the OAuth client ID,
client secret, and refresh token as `HERMES_GMAIL_CLIENT_ID`,
`HERMES_GMAIL_CLIENT_SECRET`, and `HERMES_GMAIL_REFRESH_TOKEN`. Leave
`HERMES_GMAIL_DEFAULT_DOCUMENT_KIND=job_description` for a mailbox dedicated to
nvoids requirements.

The reconciliation timer searches the Gmail `nvoids` label over the last two
days every five minutes. It lists message IDs first, removes IDs already present
in `intake_log`, and fetches only unseen messages. Normal Hermes transport
deduplication and exact-content deduplication remain active. This makes repeated
look-back scans safe, excludes unrelated account mail, and recovers messages
received before the timer was installed or during an outage.

Install the timer after OAuth is configured:

```bash
cp deploy/systemd/hermes-gmail-reconcile.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hermes-gmail-reconcile.timer
systemctl start hermes-gmail-reconcile.service
journalctl -u hermes-gmail-reconcile.service -n 100 --no-pager
```

Gmail auto-forwarding to `requirements@jobfynder.com` can be kept as a temporary
fallback, but direct reconciliation is the system of record. Do not forward to
`jobs@jobfynder.com`; Hermes currently routes requirements by the configured
requirements mailbox.
