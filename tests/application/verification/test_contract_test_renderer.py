from __future__ import annotations

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY, compile_csv_cleaner
from cgkn.application.verification import ContractTestCompiler, ContractTestRenderer, OraclePlanCompiler


def artifact():
    compilation = compile_csv_cleaner(); oracle = OraclePlanCompiler().compile_csv(compilation.obligations, CSV_DEPENDENCY_POLICY)
    plan = ContractTestCompiler().compile(compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)
    return ContractTestRenderer().render(plan, CSV_DEPENDENCY_POLICY)


def test_renderer_is_self_contained_and_deterministic() -> None:
    first, second = artifact(), artifact()
    assert first.source_hash == second.source_hash
    assert first.manifest.as_dict() == second.manifest.as_dict()
    assert "cgkn" not in first.source and "benchmarks" not in first.source
    compile(first.source, first.path, "exec")


def test_preview_regression_requires_subset_stdout_and_full_output() -> None:
    source = artifact().source
    assert 'row for row in csv.reader(io.StringIO(result.stdout)) if row] == [[\'id\', \'name\', \'city\'], [\'1\', \'Ada\', \'\']]' in source
    assert "output_rows == [['id', 'name', 'city'], ['1', 'Ada', ''], ['2', 'Lin', 'Paris']]" in source
    assert "stdout must contain full" not in source.lower()
