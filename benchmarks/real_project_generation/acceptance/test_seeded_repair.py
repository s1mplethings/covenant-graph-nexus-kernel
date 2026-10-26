from _helpers import project_root, run


def test_hidden_arithmetic_and_public_suite():
    root = project_root()
    result = run("-c", "from math_utils import add; assert add(-4, 7) == 3; assert add(0, 0) == 0")
    assert result.returncode == 0, result.stderr
    public = run("-m", "pytest", "-q")
    assert public.returncode == 0, public.stdout + public.stderr
