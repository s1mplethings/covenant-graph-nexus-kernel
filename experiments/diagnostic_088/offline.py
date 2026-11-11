import contextlib
import json
import socket
from pathlib import Path
from unittest.mock import patch


@contextlib.contextmanager
def no_provider(log):
    """Fail before transport/client construction, record even accidental attempts."""
    def deny(*args, **kwargs):
        with Path(log).open('a', encoding='utf-8') as f:
            f.write(json.dumps({'event': 'FORBIDDEN_PROVIDER_OR_NETWORK_ATTEMPT'})+'\n')
        raise RuntimeError('ITER088_OFFLINE_PROVIDER_DISABLED')
    with patch('experiments.product_eval_076_v8.live_provider.LiveClient.__init__', deny), patch.object(socket.socket, 'connect', deny), patch('urllib.request.urlopen', deny):
        yield
