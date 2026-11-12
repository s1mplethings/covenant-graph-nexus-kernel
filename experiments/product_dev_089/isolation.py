"""Same isolation, explicit bounded timeout recovery; never replay a tool."""
import hashlib
from pathlib import Path
from experiments.product_eval_076_v8.isolation import ContainerBoundary as PriorBoundary, Policy, verify_audit


class ContainerBoundary(PriorBoundary):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record('lifecycle_policy', {
            'version': 'iter089-timeout-recreate-v1',
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'timeout': 'kill all processes; recreate same mounts; return raw error; no replay',
            'backend_failure': 'stop; no host fallback',
        })

    def execute(self, action, timeout=30):
        result = super().execute(action, timeout)
        if result.get('status') != 'TIMEOUT_CONTAINER_TERMINATED':
            return result
        try:
            self.start()
        except Exception as exc:
            # A partial start must not leave an unbound environment usable.
            try:
                self.control(['rm', '-f', self.name])
            except Exception:
                pass
            self.active = False
            result = {**result, 'status': 'BLOCKED_ENV', 'recovery_error': f'{type(exc).__name__}: {exc}'}
        else:
            result = {**result, 'status': 'TIMEOUT_ENV_RECREATED'}
        self.record('timeout_recovery_result', {'action': action, 'result': result, 'automatic_replay': False})
        return result
