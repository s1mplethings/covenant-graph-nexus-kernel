from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import SchemaLoader


class SchemaValidationTest(unittest.TestCase):
    def test_all_examples_validate_against_schema(self) -> None:
        diagnostics = SchemaLoader(ROOT).validate_examples()
        self.assertEqual([], [d.as_dict() for d in diagnostics])


if __name__ == "__main__":
    unittest.main()
