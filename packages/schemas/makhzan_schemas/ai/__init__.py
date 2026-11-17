"""AI matching: the shared core the regroup, the broker, the workers and the triggers use.

- `prompt`    : the owner-approved judge prompt, verbatim, its variants and the request hash
- `hashing`   : a listing's content hash (every field that can reach a prompt)
- `policy`    : named threshold sets, the group-check threshold, the models
- `pipelines` : pipelines as data (stages = model + prompt + threshold) and the
                one transition rule every result goes through
- `triggers`  : the producer interface that queues pairs into a pipeline
- `mode`      : off / live, from `worker_state`
- `decisions` : `load_ai_same()`, what the regroup reads

The tables are in `makhzan_schemas.models` (`Ai*`); the broker's contract is
docs/ai/broker-api.md. Submodules are imported by name, not here, so that
`grouping` can import `decisions` without importing everything else.
"""
