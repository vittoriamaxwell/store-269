# store-269

A small, dependency-free Python key-value store that indexes entries by a caller-supplied timestamp, so you can ask "give me everything written between time T1 and T2" or "give me the last N writes" without scanning every key.

```python
from store_269 import Store

store = Store()
store.put("sensor:42", 17.3, timestamp=1000.0)
store.put("sensor:42", 18.1, timestamp=1001.0)

recent = store.recent(1)                 # -> [Entry(key='sensor:42', value=18.1, timestamp=1001.0)]
between = store.range(1000.5, 1001.5)   # -> [Entry(key='sensor:42', value=18.1, timestamp=1001.0)]
```

The exported names are exactly: `Store` (the store class) and `Entry` (the frozen dataclass returned by `range`, `recent`, and iteration, with `.key`, `.value`, and `.timestamp` fields). `Store` exposes `put(key, value, timestamp=None)`, `get(key)`, `range(start=None, end=None)`, `recent(n)`, `__contains__`, `__len__`, and `__iter__`.

## Why this exists

The problem: you have keys whose values change over time and you need both point lookups ("what is key X right now?") and time-windowed queries ("what was stored between T1 and T2?") over the same data. Maintaining both a dict for O(1) lookup and a sorted list for O(log n) range queries is the straightforward answer; this library is that answer, packaged so you do not have to write it again.

The trade-off: a key maps to at most one value. Overwriting a key updates the value but keeps the original timestamp. This means the store is a logical key-value map, not an append-only event log. If you need full history per key, this is the wrong library. I picked the map semantics because they match what "key-value store" usually means and they keep the data structure from accumulating stale duplicates.

## The awkward edge

`get` returns `None` both for a key that was never stored and for a key whose stored value is genuinely `None`. If you need to distinguish the two cases, check `key in store` first. There is deliberately no sentinel like `MISSING` because that would invite callers to write fragile equality checks against it; membership is the honest test.
