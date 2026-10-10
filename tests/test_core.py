import unittest

from store_269 import Entry, Store


class FakeClock:
    """A deterministic clock for tests.

    Returns a counter that advances by 1.0 each call, so timestamps are
    monotonically increasing and fully predictable.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        result = self.t
        self.t += 1.0
        return result


class TestPutAndGet(unittest.TestCase):
    def test_basic_put_and_get(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 1, timestamp=10.0)
        self.assertEqual(store.get("a"), 1)

    def test_get_missing_returns_none(self) -> None:
        store = Store(clock=FakeClock())
        self.assertIsNone(store.get("nope"))

    def test_put_without_timestamp_uses_clock(self) -> None:
        clock = FakeClock(start=5.0)
        store = Store(clock=clock)
        ts = store.put("a", "v")
        self.assertEqual(ts, 5.0)
        self.assertEqual(store.get("a"), "v")

    def test_put_key_must_be_str(self) -> None:
        store = Store(clock=FakeClock())
        with self.assertRaises(TypeError):
            store.put(123, "v", timestamp=1.0)  # type: ignore[arg-type]

    def test_put_returns_effective_timestamp(self) -> None:
        store = Store(clock=FakeClock())
        ts = store.put("a", 1, timestamp=7.0)
        self.assertEqual(ts, 7.0)

    def test_overwrite_keeps_original_timestamp(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 1, timestamp=10.0)
        store.put("a", 2, timestamp=20.0)
        # Value is updated...
        self.assertEqual(store.get("a"), 2)
        # ...but the stored timestamp is the original.
        entries = store.range()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].timestamp, 10.0)

    def test_overwrite_returns_original_timestamp(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 1, timestamp=10.0)
        returned = store.put("a", 2, timestamp=20.0)
        self.assertEqual(returned, 10.0)

    def test_contains_and_len(self) -> None:
        store = Store(clock=FakeClock())
        self.assertNotIn("a", store)
        store.put("a", 1, timestamp=1.0)
        self.assertIn("a", store)
        self.assertEqual(len(store), 1)
        store.put("b", 2, timestamp=2.0)
        self.assertEqual(len(store), 2)


class TestRange(unittest.TestCase):
    def test_full_range_sorted_ascending(self) -> None:
        store = Store(clock=FakeClock())
        store.put("b", 2, timestamp=2.0)
        store.put("a", 1, timestamp=1.0)
        store.put("c", 3, timestamp=3.0)
        entries = store.range()
        self.assertEqual([e.key for e in entries], ["a", "b", "c"])
        self.assertEqual([e.timestamp for e in entries], [1.0, 2.0, 3.0])

    def test_range_left_inclusive_right_exclusive(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 1, timestamp=1.0)
        store.put("b", 2, timestamp=2.0)
        store.put("c", 3, timestamp=3.0)
        store.put("d", 4, timestamp=4.0)
        entries = store.range(start=2.0, end=4.0)
        self.assertEqual([e.key for e in entries], ["b", "c"])

    def test_range_start_only(self) -> None:
        store = Store(clock=FakeClock())
        for i, k in enumerate(["a", "b", "c", "d"], start=1):
            store.put(k, i, timestamp=float(i))
        entries = store.range(start=3.0)
        self.assertEqual([e.key for e in entries], ["c", "d"])

    def test_range_end_only(self) -> None:
        store = Store(clock=FakeClock())
        for i, k in enumerate(["a", "b", "c", "d"], start=1):
            store.put(k, i, timestamp=float(i))
        entries = store.range(end=3.0)
        self.assertEqual([e.key for e in entries], ["a", "b"])

    def test_range_empty(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 1, timestamp=1.0)
        entries = store.range(start=100.0, end=200.0)
        self.assertEqual(entries, [])

    def test_range_returns_entry_objects(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 99, timestamp=1.0)
        entries = store.range()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertIsInstance(e, Entry)
        self.assertEqual(e.key, "a")
        self.assertEqual(e.value, 99)
        self.assertEqual(e.timestamp, 1.0)

    def test_range_with_same_timestamp_orders_by_key(self) -> None:
        store = Store(clock=FakeClock())
        # Three keys sharing timestamp 5.0.
        store.put("charlie", 3, timestamp=5.0)
        store.put("alpha", 1, timestamp=5.0)
        store.put("bravo", 2, timestamp=5.0)
        entries = store.range()
        self.assertEqual([e.key for e in entries], ["alpha", "bravo", "charlie"])


class TestRecent(unittest.TestCase):
    def test_recent_basic(self) -> None:
        store = Store(clock=FakeClock())
        for i, k in enumerate(["a", "b", "c", "d"], start=1):
            store.put(k, i, timestamp=float(i))
        entries = store.recent(2)
        self.assertEqual([e.key for e in entries], ["c", "d"])

    def test_recent_more_than_available_returns_all(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 1, timestamp=1.0)
        store.put("b", 2, timestamp=2.0)
        entries = store.recent(10)
        self.assertEqual([e.key for e in entries], ["a", "b"])

    def test_recent_zero_returns_empty(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", 1, timestamp=1.0)
        self.assertEqual(store.recent(0), [])

    def test_recent_negative_raises(self) -> None:
        store = Store(clock=FakeClock())
        with self.assertRaises(ValueError):
            store.recent(-1)

    def test_recent_rejects_bool(self) -> None:
        # bool is a subclass of int in Python; we reject it explicitly so a
        # call like recent(True) does not silently mean recent(1).
        store = Store(clock=FakeClock())
        with self.assertRaises(TypeError):
            store.recent(True)  # type: ignore[arg-type]

    def test_recent_ascending_order(self) -> None:
        # Even though this is a "recent" query, results are oldest-first so
        # callers can append to a timeline. This tests that contract.
        store = Store(clock=FakeClock())
        for i, k in enumerate(["a", "b", "c"], start=1):
            store.put(k, i, timestamp=float(i))
        entries = store.recent(2)
        self.assertEqual([e.timestamp for e in entries], [2.0, 3.0])


class TestIteration(unittest.TestCase):
    def test_iter_sorted(self) -> None:
        store = Store(clock=FakeClock())
        store.put("b", 2, timestamp=2.0)
        store.put("a", 1, timestamp=1.0)
        store.put("c", 3, timestamp=3.0)
        keys = [e.key for e in store]
        self.assertEqual(keys, ["a", "b", "c"])


class TestEdgeCases(unittest.TestCase):
    def test_none_value_is_preserved(self) -> None:
        store = Store(clock=FakeClock())
        store.put("a", None, timestamp=1.0)
        # get returns None for missing keys too, so we confirm membership first.
        self.assertIn("a", store)
        self.assertIsNone(store.get("a"))
        entries = store.range()
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].value)

    def test_int_timestamp_accepted(self) -> None:
        store = Store(clock=FakeClock())
        ts = store.put("a", 1, timestamp=5)
        self.assertEqual(ts, 5.0)
        self.assertIsInstance(ts, float)

    def test_empty_store_operations(self) -> None:
        store = Store(clock=FakeClock())
        self.assertEqual(len(store), 0)
        self.assertEqual(store.range(), [])
        self.assertEqual(store.recent(5), [])
        self.assertIsNone(store.get("anything"))
        self.assertEqual(list(store), [])


if __name__ == "__main__":
    unittest.main()
