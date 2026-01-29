import os
import pathlib
import sys
import types
import unittest

TEST_TMP = pathlib.Path.cwd() / ".tmp_test_state"
TEST_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("STATE_DB_FILE", str(TEST_TMP / "state.db"))
os.environ.setdefault("LOG_FILE", str(TEST_TMP / "tdarr_sync.log"))

def _ensure_pydantic():
    try:
        import pydantic  # noqa: F401
        return
    except Exception:
        pass

    stub = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **data):
            for key, value in data.items():
                setattr(self, key, value)

    def _field(default=None, **_kwargs):
        return default

    stub.BaseModel = _BaseModel
    stub.Field = _field
    sys.modules["pydantic"] = stub


def _load_restore_selection():
    _ensure_pydantic()

    from api.restore_service import RestoreSelectionError, parse_selection

    return RestoreSelectionError, parse_selection


RestoreSelectionError, parse_selection = _load_restore_selection()


class ParseSelectionTests(unittest.TestCase):
    def test_all_keyword(self):
        self.assertEqual(parse_selection("all", 4), [1, 2, 3, 4])

    def test_range_and_values(self):
        self.assertEqual(parse_selection("1,3,5-7", 8), [1, 3, 5, 6, 7])

    def test_deduplicates_and_order(self):
        self.assertEqual(parse_selection("2,3,2,1-3", 5), [2, 3, 1])

    def test_trims_whitespace(self):
        self.assertEqual(parse_selection(" 1 - 2 , 4 ", 5), [1, 2, 4])

    def test_requires_selection(self):
        with self.assertRaises(RestoreSelectionError):
            parse_selection("", 3)

    def test_rejects_out_of_range(self):
        with self.assertRaises(RestoreSelectionError):
            parse_selection("6", 5)

    def test_rejects_invalid_range(self):
        with self.assertRaises(RestoreSelectionError):
            parse_selection("3-1", 5)


if __name__ == "__main__":
    unittest.main()
