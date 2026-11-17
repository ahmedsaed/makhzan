"""The AI-matching worker: leases rendered requests from the broker, scores them, posts scores.

One process serves the model key(s) its TOML configuration names (`config`), talks only
to the broker (`broker`), loads each model once in-process on the validated scoring path
(`judges`, pinned by `pins`), and runs one session from hello to the last release
(`run`). `fake_broker` is a contract-following stand-in for tests and `parity`, which
compares the worker's scores with stored ones. docs/ai/worker.md is the reference.

    python -m makhzan_ml.worker --config /etc/makhzan-ai/worker.toml
    python -m makhzan_ml.worker --config worker.toml --check     # validate and exit
"""
