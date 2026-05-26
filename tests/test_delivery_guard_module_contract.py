from __future__ import annotations

import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry


class DeliveryGuardModuleContractTest(unittest.TestCase):
    def test_delivery_package_requires_delivery_ready_truth(self) -> None:
        module = ContractRegistry(ROOT).modules["module.delivery.package@1"]
        self.assertTrue(module["metadata"]["requires_delivery_ready_truth"])


if __name__ == "__main__":
    unittest.main()
