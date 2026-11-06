"""HERMES-950 daily Telegram digest.

Sends a short daily summary to the same Telegram channel already used
for operational alerts (see /opt/hermes/scripts/telegram_alert.sh) --
taxonomy growth, review-queue health, yesterday's triage activity, LLM
cost, and parsing quality. A passive companion to the in-app Reports
page (app/reporting/service.py, same underlying data): this shows up
on its own each morning instead of requiring someone to go look.

Scheduled via a host systemd timer, same shape as hermes-taxonomy-
triage.timer, timed to run shortly after the daily triage job so the
digest reflects that day's cleared backlog rather than the pre-triage
numbers.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from app.reporting.service import get_dashboard_overview


def _format_digest(data: dict) -> str:
    tax = data["taxonomy"]
    queue = data["queue_health"]
    cost = data["llm_cost"]
    quality = data["parsing_quality"]

    activity = data["triage_activity"]
    today_totals = {"approved_automated": 0, "approved_human": 0, "rejected_automated": 0, "rejected_human": 0}
    if activity:
        latest = activity[-1]
        today_totals = latest

    cost_line = "Cost data unavailable"
    if cost.get("available") and cost.get("days"):
        last_day = cost["days"][-1]
        cost_line = f"Yesterday: ${last_day['cost']:.2f} | Last 30d total: ${cost.get('total_cost', 0):.2f}"

    quality_line = "No drafts parsed in the last 7 days"
    if quality["total_drafts"]:
        conf_pct = round((quality["avg_confidence"] or 0) * 100)
        quality_line = (
            f"{quality['total_drafts']} drafts | avg confidence {conf_pct}% | "
            f"{quality['needs_review_pct']}% need review"
        )

    return (
        "📊 Hermes Daily Digest\n\n"
        f"Taxonomy: {tax['total_skills']} skills (+{tax['skills_added_7d']} this week), "
        f"{tax['total_job_titles']} job titles (+{tax['job_titles_added_7d']} this week)\n\n"
        f"Review queue: {queue['skill']['pending_count']} skills, "
        f"{queue['job_title']['pending_count']} titles, "
        f"{queue['boilerplate_line']['pending_count']} boilerplate lines pending\n\n"
        f"Latest triage: {today_totals['approved_automated']} auto-approved, "
        f"{today_totals['rejected_automated']} auto-rejected, "
        f"{today_totals['approved_human'] + today_totals['rejected_human']} human-reviewed\n\n"
        f"LLM cost -- {cost_line}\n\n"
        f"Parsing quality (7d) -- {quality_line}"
    )


def _pipeline_section() -> str:
    """Job-posting pipeline health (best effort: never breaks the digest)."""
    try:
        from app.drafts.pipeline import get_pipeline_stats
        from app.understanding.taxonomy.automation import get_automation_status

        stats = get_pipeline_stats(14)
        fill = stats["fill_rates_pct"]
        outbox = stats["outbox"]
        clusters = stats["clusters"]
        auto = get_automation_status()
        last = (auto.get("last_run") or {}).get("ran_at", "never")[:16]
        lines = [
            "\n\n🧭 Job pipeline (14d)",
            f"{stats['considered']} live posts | {stats['ready_pct']}% ready for Core "
            f"({stats['only_employment_type_missing']} missing only employment type)",
            f"Fill: title {fill['job_title']}% | location {fill['location']}% | employment {fill['employment_type']}% | "
            f"work mode {fill['work_mode']}% | rate {fill['rate']}%",
            f"Distinct roles: {clusters['clusters']} ({clusters['clusters_with_duplicates']} with duplicates)",
            f"Core outbox: {outbox['states'] or 'empty'} | push {'ON' if outbox['dispatch_enabled'] else 'OFF'} "
            f"| Core pushes so far: {stats['core_pushes'] or 'none'}",
            f"Review automation last run: {last} | auto-blocks active: {auto['auto_blocks_active']}",
        ]
        try:
            from app.drafts.expiry import get_expiry_status

            expiry = get_expiry_status()
            lines.append(f"Expiry: {expiry['due_now']} due, {expiry['expired_last_24h']} removed in 24h, "
                         f"{expiry['archived_restorable']} restorable")
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"\n\n🧭 Job pipeline: unavailable ({type(exc).__name__})"


def send_telegram_message(text: str) -> None:
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=body,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Telegram sendMessage returned status {resp.status}")


def main() -> int:
    data = get_dashboard_overview()
    text = _format_digest(data) + _pipeline_section()
    print(text)

    if not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        print("\n(TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set -- printed only, not sent.)")
        return 0

    try:
        send_telegram_message(text)
    except (urllib.error.URLError, RuntimeError, KeyError) as e:
        print(f"Failed to send Telegram digest: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
