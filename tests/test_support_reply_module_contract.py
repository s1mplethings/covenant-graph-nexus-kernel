from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry


class SupportReplyModuleContractTest(unittest.TestCase):
    def test_support_reply_and_public_guard_shape(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=True)
        reply = registry.modules["module.support.reply.orchestrate@1"]
        guard = registry.modules["module.public.send.guard@1"]
        self.assertTrue(reply["metadata"]["customer_facing_reply_composer"])
        self.assertTrue(guard["metadata"]["last_public_text_guard"])
        self.assertFalse(reply["effects"]["provider_call"])
        self.assertFalse(guard["effects"]["network"])


if __name__ == "__main__":
    unittest.main()
