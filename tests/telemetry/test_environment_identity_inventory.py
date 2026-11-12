import importlib.metadata
import platform
import sys
import hashlib
from pathlib import Path
import pytest
from cgkn.telemetry import lean
from cgkn.artifacts.hash import content_hash

pytestmark = [pytest.mark.boundary]

def test_environment_inventory_preserves_full_identity_with_one_metadata_read(monkeypatch):
    class Distribution:
        reads=0
        @property
        def metadata(self):
            self.reads+=1
            return {'Name':'fixture-package','Version':'1.2.3'}
        @property
        def version(self):
            raise AssertionError('second parsing of metadata is unnecessary')
    d=Distribution()
    monkeypatch.setattr(importlib.metadata,'distributions',lambda:[d])
    lean.environment_identity.cache_clear()
    captured=[]
    monkeypatch.setattr(lean,'content_hash',lambda value:captured.append(value) or content_hash(value))
    try:
        actual=lean.environment_identity()
        assert d.reads==1 and captured[0]['packages']==[('fixture-package','1.2.3')]
        assert captured[0]['python']==sys.version and captured[0]['platform']==platform.platform()
        root=Path(lean.__file__).resolve().parents[1]
        assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==h for name,h in captured[0]['execution_sources'].items())
        assert actual==content_hash(captured[0])
        assert lean.environment_identity()==actual and d.reads==1
    finally:lean.environment_identity.cache_clear()


def test_package_description_is_excluded_but_metadata_identity_is_retained():
    class Distribution:
        def read_text(self, name):
            assert name=='METADATA'
            return 'Metadata-Version: 2.1\r\nName: Exact-Name\r\nVersion: 1.0+local\r\n\r\nName: misleading-body\n' + 'body '*100000
        @property
        def metadata(self):raise AssertionError('description body should not be parsed')
    assert lean._package_identity(Distribution())==('Exact-Name','1.0+local')


def test_folded_package_identity_uses_standard_metadata_normalization():
    class Distribution:
        def read_text(self,name):return 'Name: first\n continued\nVersion: 1\n\nbody'
        @property
        def metadata(self):return {'Name':'canonical folded value','Version':'1'}
    assert lean._package_identity(Distribution())==('canonical folded value','1')
