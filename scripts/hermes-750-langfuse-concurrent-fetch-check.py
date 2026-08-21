from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.prompt_runtime.langfuse_prompts as langfuse_prompts


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_live_fetch_is_correct_and_reasonably_fast() -> None:
    langfuse_prompts._cache['registry'] = None
    langfuse_prompts._cache['prompts'] = {}
    langfuse_prompts._cache['fetched_at'] = 0.0

    t0 = time.time()
    registry = langfuse_prompts.list_prompts()
    elapsed = time.time() - t0

    require(registry.prompt_count > 0, 'expected at least one prompt from a live registry fetch')
    require(
        elapsed < 20.0,
        f'concurrent fetch took {elapsed:.2f}s - expected well under the old ~33s sequential baseline',
    )

    prompt_ids = {p.prompt_id for p in registry.prompts}
    require(len(prompt_ids) == registry.prompt_count, 'prompt_count must match the number of distinct prompt_ids returned')


def test_one_failing_prompt_does_not_abort_the_whole_refresh() -> None:
    langfuse_prompts._cache['registry'] = None
    langfuse_prompts._cache['prompts'] = {}
    langfuse_prompts._cache['fetched_at'] = 0.0

    real_get = langfuse_prompts._get
    call_count = {'n': 0}

    def flaky_get(path: str):
        if path.startswith(langfuse_prompts.PROMPTS_PATH + '/'):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise RuntimeError('simulated transient failure for the first prompt detail fetch')
        return real_get(path)

    langfuse_prompts._get = flaky_get

    try:
        registry = langfuse_prompts.list_prompts()
    finally:
        langfuse_prompts._get = real_get

    require(
        registry.prompt_count > 0,
        'one simulated failed prompt fetch must not take down the entire registry refresh',
    )
    require(call_count['n'] > 1, 'the flaky detail endpoint must have been called for more than one prompt')


def test_fetch_concurrency_setting_is_read_from_env(monkeypatch=None) -> None:
    import os

    original = os.environ.get('HERMES_LANGFUSE_PROMPT_FETCH_CONCURRENCY')

    try:
        os.environ['HERMES_LANGFUSE_PROMPT_FETCH_CONCURRENCY'] = '3'
        require(langfuse_prompts._fetch_concurrency() == 3, 'concurrency setting must read from env')

        os.environ['HERMES_LANGFUSE_PROMPT_FETCH_CONCURRENCY'] = 'not-a-number'
        require(
            langfuse_prompts._fetch_concurrency() == langfuse_prompts.DEFAULT_FETCH_CONCURRENCY,
            'an invalid concurrency value must fall back to the default, not crash',
        )

        os.environ['HERMES_LANGFUSE_PROMPT_FETCH_CONCURRENCY'] = '0'
        require(langfuse_prompts._fetch_concurrency() == 1, 'concurrency must be clamped to at least 1')
    finally:
        if original is None:
            os.environ.pop('HERMES_LANGFUSE_PROMPT_FETCH_CONCURRENCY', None)
        else:
            os.environ['HERMES_LANGFUSE_PROMPT_FETCH_CONCURRENCY'] = original


def run() -> None:
    tests = [
        test_live_fetch_is_correct_and_reasonably_fast,
        test_one_failing_prompt_does_not_abort_the_whole_refresh,
        test_fetch_concurrency_setting_is_read_from_env,
    ]

    for test in tests:
        test()
        print(f'PASS: {test.__name__}')

    print('PASS: HERMES-750 concurrent Langfuse prompt fetch checks')


if __name__ == '__main__':
    run()
