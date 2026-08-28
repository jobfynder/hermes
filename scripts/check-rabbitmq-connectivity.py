#!/usr/bin/env python3
"""Validate INTEL-1 can authenticate to COMM-1 RabbitMQ and see Graph intake."""

import os
import sys

import pika


QUEUE_NAME = "comm.intake.microsoft_graph"


def main() -> None:
    rabbitmq_url = os.getenv("RABBITMQ_URL", "").strip()
    if not rabbitmq_url:
        raise SystemExit("FAIL: RABBITMQ_URL is required")

    connection = None
    try:
        parameters = pika.URLParameters(rabbitmq_url)
        parameters.socket_timeout = 10
        parameters.stack_timeout = 15
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        result = channel.queue_declare(queue=QUEUE_NAME, passive=True)
        print(
            f"PASS: authenticated RabbitMQ connection; queue={QUEUE_NAME} "
            f"messages={result.method.message_count} "
            f"consumers={result.method.consumer_count}"
        )
    except Exception as exc:
        print(f"FAIL: RabbitMQ connectivity check failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        if connection is not None and connection.is_open:
            connection.close()


if __name__ == "__main__":
    main()
