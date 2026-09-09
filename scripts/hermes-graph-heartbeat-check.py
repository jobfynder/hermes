"""Integration check against a disposable broker; never uses production queues."""
import importlib.util
import json
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from uuid import uuid4
import pika


def slow_processing(_notification):
    # Longer than four negotiated heartbeat intervals, with CPU work too.
    deadline = time.monotonic() + 9
    while time.monotonic() < deadline:
        sum(i*i for i in range(10000))
    return 'processed'


def main():
    spec = importlib.util.spec_from_file_location('consumer', Path(__file__).with_name('hermes-850-graph-notification-consumer.py'))
    consumer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consumer)
    parameters = pika.ConnectionParameters('hermes-fix-test-rabbit', heartbeat=2)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    queue = 'hermes-reliability-' + str(uuid4())
    channel.queue_declare(queue, auto_delete=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_publish('', queue, json.dumps({'notification': {'resource':'synthetic'}}))
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        class Executor:
            def submit(self, _function, notification):
                return pool.submit(slow_processing, notification)
        consumer._executor = Executor()
        channel.basic_consume(queue, consumer._on_message)
        completed = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not completed:
            connection.process_data_events(time_limit=0.2)
            for future, delivery_channel, method, envelope, started in list(consumer._pending):
                if future.done():
                    consumer._finish_message(delivery_channel, method, envelope, future.result())
                    completed = True
        assert completed and connection.is_open
        assert channel.queue_declare(queue, passive=True).method.message_count == 0
        print('PASS: 9-second CPU-bound processing survives 2-second heartbeats and acknowledges successfully')
    connection.close()


if __name__ == '__main__':
    main()
