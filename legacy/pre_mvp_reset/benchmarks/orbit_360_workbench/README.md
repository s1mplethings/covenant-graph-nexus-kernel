# ORBIT-360

ORBIT-360 is a dependency-aware workload and evidence workbench built as a real CGKN scale-test project. Its default scenario materializes 360 deterministic work-unit descriptors in layers of width 35, executes them, checkpoints results, resumes verified work, and invalidates only the transitive downstream closure after a targeted repair.

- [项目愿景](PROJECT_VISION.md)
- [使用方式](USAGE.md)
- [测试计划](TEST_PLAN.md)
- [实测结果](EXPECTED_RESULTS.md)

The project uses only the Python standard library at runtime. It never executes materialized source code or accepts an arbitrary command. Its reports are benchmark support artifacts with formal evidence status `NOT_EVALUATED`; they do not authorize CGKN packaging or delivery.
