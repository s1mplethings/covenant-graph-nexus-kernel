from __future__ import annotations

from .contracts import SupervisionReceipt


def compact_usage(receipt: SupervisionReceipt) -> dict[str, object]:
    from .transport import SupervisedHttpTransport
    return SupervisedHttpTransport.usage(receipt)

