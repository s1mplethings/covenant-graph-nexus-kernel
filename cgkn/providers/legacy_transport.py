"""Historical JSON sender name delegates to the canonical budgeted Gateway.

The token argument is retained for signature compatibility. It never authorizes
an independent sender, and missing shared admission fails before transport.
"""


def post_json_once(endpoint, payload, token, timeout_sec):
    from .canonical_gateway_adapter import post_payload
    return post_payload(payload, timeout_sec, endpoint=endpoint), ''
