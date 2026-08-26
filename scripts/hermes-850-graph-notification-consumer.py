#!/usr/bin/env python3
"""Consumes Microsoft Graph mail-change notifications from RabbitMQ and
runs them through Hermes's existing fetch -> normalize -> parse pipeline.

This is the missing link in the new webhook architecture. As things stand
without this script:

  jobfynder-infra's COMM gateway (hooks.jobfynder.com/microsoft-graph/mail)
  checks each notification's clientState and durably publishes it to the
  "comm.intake.microsoft_graph" RabbitMQ queue, then acknowledges Graph
  immediately. Nothing reads that queue. Notifications just accumulate.

This script is the reader. For each notification it calls the exact same
three functions app/routers/microsoft_graph_provider.py's old synchronous
webhook handler already calls -- fetch_graph_message, normalize_graph_message,
process_channel_intake -- so the fetch-and-parse logic itself is reused
unchanged, not rebuilt. Only the trigger changes: a queue message instead
of an inline HTTP request.

Retry/dead-letter: a notification that fails processing (Graph API
timeout, token failure, etc.) is republished to the SAME retry/dead-letter
RabbitMQ topology jobfynder-infra's comm_gateway already declares for its
Telegram queue -- just with the Graph-specific queue/routing-key names
(see GRAPH_RETRY_* / GRAPH_DEAD_LETTER_* below, which must match
communication/comm_gateway/config.py in the jobfynder-infra repo exactly).
After GRAPH_MAX_RETRIES failed attempts with exponential backoff, the
message lands in the Graph dead-letter queue instead of being silently
dropped -- something can inspect it later.

This script declares that same topology defensively at startup (the exact
same declare calls jobfynder-infra's comm_gateway makes) so it works
correctly regardless of which of the two services happens to start first.
RabbitMQ queue/exchange declarations are idempotent as long as the
properties match, so this is safe to run alongside comm_gateway's own
declaration, not a conflicting second definition.

Run this as its own long-lived process, separate from the hermes-api web
process (see the hermes-graph-consumer service in docker-compose.yml). It
is a blocking consume loop, not a request handler.

Required environment (see .env.example):
  RABBITMQ_URL                 - same RabbitMQ instance the COMM gateway
                                  publishes to. Not yet in Hermes's .env;
                                  add it.
  HERMES_MS_GRAPH_CLIENT_STATE - must be the SAME value set in
                                  jobfynder-infra's comm_gateway env
                                  (HERMES_MS_GRAPH_CLIENT_STATE there too).
                                  If they don't match exactly, every
                                  notification gets rejected here even
                                  though the gateway already accepted it.
  HERMES_MS_GRAPH_CLIENT_ID / HERMES_MS_GRAPH_CLIENT_SECRET /
  HERMES_MS_GRAPH_TENANT_ID    - the Azure app registration credentials.

Exits non-zero on any unhandled failure (including "can't reach RabbitMQ
at startup") so a process supervisor (Docker's restart policy here)
notices and restarts it, rather than the process silently dying and
nothing consuming the queue with no signal that happened.
"""
from __future__ import annotations

import json
import logging
import os
import sys

import pika

from app.channels.models import ChannelIntakeRequest
from app.channels.service import process_channel_intake
from app.providers.microsoft_graph.service import (
    fetch_graph_message,
    normalize_graph_message,
    verify_notification_client_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("hermes.graph_consumer")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://rabbitmq:5672/")

INTAKE_EXCHANGE = "comm.intake"
RETRY_EXCHANGE = "comm.intake.retry"
DEAD_LETTER_EXCHANGE = "comm.intake.dead"

QUEUE_NAME = "comm.intake.microsoft_graph"
GRAPH_INTAKE_ROUTING_KEY = "microsoft_graph"

GRAPH_RETRY_QUEUE = "comm.intake.microsoft_graph.retry"
GRAPH_RETRY_ROUTING_KEY = "microsoft_graph.retry"

GRAPH_DEAD_LETTER_QUEUE = "comm.intake.microsoft_graph.dead"
GRAPH_DEAD_LETTER_ROUTING_KEY = "microsoft_graph.dead"

GRAPH_RETRY_BACKOFF_MS = [5_000, 15_000, 60_000, 300_000, 900_000]
GRAPH_MAX_RETRIES = len(GRAPH_RETRY_BACKOFF_MS)


def _declare_topology(channel) -> None:
    channel.exchange_declare(exchange=INTAKE_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(exchange=RETRY_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(exchange=DEAD_LETTER_EXCHANGE, exchange_type="direct", durable=True)

    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.queue_bind(queue=QUEUE_NAME, exchange=INTAKE_EXCHANGE, routing_key=GRAPH_INTAKE_ROUTING_KEY)

    channel.queue_declare(
        queue=GRAPH_RETRY_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": INTAKE_EXCHANGE,
            "x-dead-letter-routing-key": GRAPH_INTAKE_ROUTING_KEY,
        },
    )
    channel.queue_bind(queue=GRAPH_RETRY_QUEUE, exchange=RETRY_EXCHANGE, routing_key=GRAPH_RETRY_ROUTING_KEY)

    channel.queue_declare(queue=GRAPH_DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(
        queue=GRAPH_DEAD_LETTER_QUEUE,
        exchange=DEAD_LETTER_EXCHANGE,
        routing_key=GRAPH_DEAD_LETTER_ROUTING_KEY,
    )


def _handle_notification(notification: dict) -> str:
    """Returns 'processed', 'rejected', or 'fetch_failed'."""
    if not verify_notification_client_state(notification):
        logger.warning(
            "Rejected Graph notification with invalid/missing clientState "
            "(resource=%s). This should already have been filtered by the "
            "COMM gateway before it reached the queue -- seeing it here "
            "means something is publishing to this queue without going "
            "through that check, or HERMES_MS_GRAPH_CLIENT_STATE doesn't "
            "match between the two services.",
            notification.get("resource"),
        )
        return "rejected"

    message = fetch_graph_message(notification.get("resource"))
    if not message:
        logger.warning(
            "Could not fetch Graph message for resource=%s -- missing "
            "credentials, a deleted message, or a Graph API failure. "
            "fetch_graph_message() never raises, so this log line is the "
            "only signal available. If this keeps happening, check the "
            "HERMES_MS_GRAPH_* credentials, not this script.",
            notification.get("resource"),
        )
        return "fetch_failed"

    normalized = normalize_graph_message(message)
    channel_request = ChannelIntakeRequest(**normalized)
    result = process_channel_intake(channel_request)

    logger.info(
        "Processed Graph message source_message_id=%s intake_status=%s "
        "document_kind=%s requires_review=%s",
        result.source_message_id,
        result.intake_status,
        result.document_kind,
        result.requires_review,
    )
    return "processed"


def _publish(channel, exchange: str, routing_key: str, envelope: dict, expiration_ms: int | None = None) -> None:
    properties_kwargs = {"delivery_mode": 2}
    if expiration_ms is not None:
        properties_kwargs["expiration"] = str(expiration_ms)

    channel.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=json.dumps(envelope).encode("utf-8"),
        properties=pika.BasicProperties(**properties_kwargs),
    )


def _on_message(channel, method, _properties, body: bytes) -> None:
    try:
        envelope = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Dropping unparseable queue message: %r", body[:200])
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    notification = envelope.get("notification")
    if not isinstance(notification, dict):
        logger.error("Dropping envelope with no notification object: %r", envelope)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    try:
        outcome = _handle_notification(notification)
    except Exception:
        logger.exception(
            "Unhandled error processing Graph notification (resource=%s)",
            notification.get("resource"),
        )
        outcome = "error"

    if outcome in {"processed", "rejected"}:
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    retry_count = envelope.get("retry_count", 0)
    channel.basic_ack(delivery_tag=method.delivery_tag)

    if retry_count < GRAPH_MAX_RETRIES:
        envelope["retry_count"] = retry_count + 1
        delay_ms = GRAPH_RETRY_BACKOFF_MS[retry_count]
        _publish(channel, RETRY_EXCHANGE, GRAPH_RETRY_ROUTING_KEY, envelope, expiration_ms=delay_ms)
        logger.warning(
            "Queued Graph notification for retry in %dms (attempt %d/%d) resource=%s",
            delay_ms,
            envelope["retry_count"],
            GRAPH_MAX_RETRIES,
            notification.get("resource"),
        )
    else:
        dead_envelope = {**envelope, "dead_letter_reason": outcome}
        _publish(channel, DEAD_LETTER_EXCHANGE, GRAPH_DEAD_LETTER_ROUTING_KEY, dead_envelope)
        logger.error(
            "Dead-lettered Graph notification after %d failed attempts, "
            "resource=%s -- see %s. If this is happening often, something "
            "is structurally broken (bad credentials, a Graph API outage), "
            "not a one-off blip.",
            GRAPH_MAX_RETRIES,
            notification.get("resource"),
            GRAPH_DEAD_LETTER_QUEUE,
        )


def main() -> None:
    logger.info("hermes-graph-consumer starting, queue=%s", QUEUE_NAME)

    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    _declare_topology(channel)
    channel.basic_qos(prefetch_count=10)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=_on_message)

    logger.info("hermes-graph-consumer ready, consuming from %s", QUEUE_NAME)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("hermes-graph-consumer crashed")
        sys.exit(1)
