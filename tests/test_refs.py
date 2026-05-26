from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core.refs import is_valid_ref, parse_ref


class RefsTest(unittest.TestCase):
    def test_parse_valid_refs(self) -> None:
        ref = parse_ref("artifact.goal@1")
        self.assertEqual("artifact", ref.kind)
        self.assertEqual("goal", ref.name)
        self.assertEqual("1", ref.version)
        self.assertTrue(is_valid_ref("module.intent.expand@1", "module"))

    def test_reject_stringly_refs(self) -> None:
        for value in ("Goal", "module.plan.generate", "flow x@1", "artifact.goal"):
            self.assertFalse(is_valid_ref(value))


if __name__ == "__main__":
    unittest.main()
