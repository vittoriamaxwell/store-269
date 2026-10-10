"""Core implementation of the time-ordered key-value store.

Design decisions (documented so future readers know the rules, not just the
mechanics):

* A key maps to at most one value at a time. Calling ``put`` with a key that
  already exists does NOT create a second historical entry; it overwrites the
  value in place and keeps the ORIGINAL timestamp. This makes the store behave
  like a logical dictionary rather than an append-only event log. The README
  states this plainly because it is the one choice a reader might assume the
  other way around.

* Timestamps are opaque floats supplied by the caller (or a caller-injected
  clock callable). The store never reads the wall clock itself. This keeps every
  operation deterministic and lets tests control ordering exactly.

* The primary index is a dict for O(1) point lookups. A secondary list of
  ``(timestamp, key)`` pairs is kept sorted by timestamp via ``bisect``. Range
  queries and "most recent N" queries binary-search that list. Keeping the list
  flat and sorted is simpler than a balanced tree, and in practice the constant
  factors are fine for the moderate sizes this library targets. The trade-off is
  that ``put`` on an existing key is O(n) because we remove the old tuple before
  reinserting; we accept that because the whole point of the overwrite rule is
  that keys do not pile up.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Tuple


@dataclass(frozen=True)
class Entry:
    """A single stored record returned by queries.

    Attributes:
        key:       The key under which the value was stored.
        value:     The value.
        timestamp: The float timestamp associated with the entry.
    """

    key: str
    value: object
    timestamp: float


class Store:
    """A key-value store indexed by timestamp.

    Args:
        clock: Optional callable returning a float, used as the timestamp
            when ``put`` is called without an explicit ``timestamp``. The
            store never calls this on its own initiative; it only forwards
            user writes through it. Defaults to ``time.time``.

    Raises:
        Nothing during construction.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        # Import lazily so callers who always pass an explicit timestamp never
        # pay for importing ``time`` and never risk touching the wall clock.
        if clock is None:
            import time

            clock = time.time
        self._clock = clock
        # Maps key -> (timestamp, value). Single source of truth for "what a
        # key currently holds".
        self._data: Dict[str, Tuple[float, object]] = {}
        # Sorted list of (timestamp, key) tuples. Sorted by timestamp; ties
        # broken by key (str) order, which keeps the list deterministically
        # ordered even when two writes share a timestamp.
        self._order: List[Tuple[float, str]] = []

    def put(self, key: str, value: object, timestamp: float | None = None) -> float:
        """Store ``value`` under ``key``.

        If the key already exists, its value is overwritten IN PLACE and the
        ORIGINAL timestamp is preserved. This is a deliberate rule: the store is
        a logical key-value map, not an append-only log. See the module
        docstring for the rationale.

        Args:
            key:       The key to store under. Must be a str.
            value:     The value to store. Any object.
            timestamp: Optional explicit timestamp (float). If omitted, the
                       store's ``clock`` callable is called to produce one.

        Returns:
            The timestamp in effect for the entry after this write (which, for
            an overwrite, is the pre-existing timestamp).
        """
        if not isinstance(key, str):
            raise TypeError("key must be a str")

        if timestamp is None:
            timestamp = float(self._clock())
        else:
            # Normalise so callers can pass ints without creating inconsistent
            # types internally. We do NOT reject non-numeric types here; Python
            # will raise a clear TypeError at the comparison sites below if the
            # caller passes something truly unusable, and rejecting e.g.
            # ``decimal.Decimal`` would be needlessly strict.
            timestamp = float(timestamp)

        existing = self._data.get(key)
        if existing is not None:
            old_ts, _ = existing
            # Overwrite value, keep old timestamp. The ordering list is
            # unchanged because the (old_ts, key) tuple is still valid.
            self._data[key] = (old_ts, value)
            return old_ts

        self._data[key] = (timestamp, value)
        bisect.insort(self._order, (timestamp, key))
        return timestamp

    def get(self, key: str) -> object | None:
        """Return the current value for ``key``, or ``None`` if absent."""
        existing = self._data.get(key)
        if existing is None:
            return None
        return existing[1]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def range(
        self,
        start: float | None = None,
        end: float | None = None,
    ) -> List[Entry]:
        """Return entries whose timestamp falls in ``[start, end)``.

        The interval is closed on the left and open on the right, matching the
        convention of ``range()`` and most slicing APIs. ``start`` is inclusive;
        ``end`` is exclusive. Either bound may be omitted (or ``None``) to mean
        "unbounded" on that side.

        Returns a list of :class:`Entry` objects sorted by timestamp ascending.
        Entries sharing a timestamp are ordered by key ascending.
        """
        # ``bisect_left`` with a tuple ``(start, "")`` finds the first index whose
        # tuple is >= (start, ""), i.e. the first entry with timestamp >= start.
        # Using "" as the key component means any key sorts after it, so the
        # left bound is inclusive on the timestamp regardless of the key.
        if start is None:
            lo = 0
        else:
            start = float(start)
            lo = bisect.bisect_left(self._order, (start, ""))

        # For the right bound we want the first index whose tuple is
        # >= (end, MAX_KEY) so that an entry exactly at ``end`` is excluded. We
        # don't know a max string, so instead we ask for the first index whose
        # tuple is strictly > (end, ""). ``bisect_right`` returns the insertion
        # point to the right of any existing (end, "") entries, which is
        # exactly the first tuple with timestamp strictly greater than ``end``
        # (or a tuple equal to ``(end, k)`` for some non-empty k, which also
        # satisfies the timestamp being == end and thus should be excluded).
        if end is None:
            hi = len(self._order)
        else:
            end = float(end)
            hi = bisect.bisect_right(self._order, (end, ""))

        return [self._entry_for(t, k) for (t, k) in self._order[lo:hi]]

    def recent(self, n: int) -> List[Entry]:
        """Return the ``n`` entries with the largest timestamps.

        Returns a list sorted by timestamp ascending (oldest of the selected
        first, newest last). If ``n`` exceeds the number of entries, every
        entry is returned. ``n`` must be a non-negative integer.

        Rationale for ascending order even though this is a "recent" query:
        callers usually want to append the result to a timeline or display it
        oldest-to-newest. A caller who wants newest-first can call
        ``result[::-1]``.
        """
        if not isinstance(n, int) or isinstance(n, bool):
            raise TypeError("n must be an int")
        if n < 0:
            raise ValueError("n must be non-negative")

        if n == 0:
            return []

        start = max(len(self._order) - n, 0)
        return [self._entry_for(t, k) for (t, k) in self._order[start:]]

    def __iter__(self) -> Iterator[Entry]:
        """Iterate over all entries in timestamp-ascending order."""
        for (t, k) in self._order:
            yield self._entry_for(t, k)

    def _entry_for(self, timestamp: float, key: str) -> Entry:
        """Build an :class:`Entry` for a (timestamp, key) from the order list.

        The value is fetched from ``self._data`` so there is a single source of
        truth for the current value. This matters because ``put`` on an existing
        key keeps the old timestamp but updates the value; the ordering list
        would otherwise hold a stale pointer to the old value.
        """
        return Entry(key=key, value=self._data[key][1], timestamp=timestamp)
