"""Process-local editable dependency overlay, never a global Python change.

The frozen Promotion run records its original interpreter. Explicit launchers
set this directory on PYTHONPATH and name the isolated editable installation.
Child processes inherit the same dependency route and interpreter identity.
"""
import os
import site
from pathlib import Path

location = os.environ.get('VERIARBOR_EDITABLE_SITE')
if location:
    path = Path(location).resolve()
    if not path.is_dir() or not list(path.glob('veriarbor-*.dist-info')):
        raise RuntimeError('missing isolated VeriArbor distribution metadata')
    site.addsitedir(str(path))
