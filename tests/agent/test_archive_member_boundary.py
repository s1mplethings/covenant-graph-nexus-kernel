import pytest
from experiments.product_dev_113.paths import safe_member

@pytest.mark.parametrize("name", ["../private", "..\\private", "C:\\host\\private", "C:private", "/private", "a/../../private"])
def test_host_materialization_rejects_cross_platform_path_variants(name):
    with pytest.raises(ValueError):safe_member(name)

def test_nested_public_files_keep_their_identity():
    assert safe_member("data/input.json").parts == ("data","input.json")
