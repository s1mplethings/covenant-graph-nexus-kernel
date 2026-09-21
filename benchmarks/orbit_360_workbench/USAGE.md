# ORBIT-360 使用方式

以下命令均在本目录执行：

```powershell
cd D:\CGKN\benchmarks\orbit_360_workbench
```

## 1. 运行自动测试

```powershell
python -m unittest discover -s tests -v
```

## 2. 创建默认 360 单元工作区

```powershell
python -m orbit360 plan --workspace workspace
```

输出包括：

- `workspace/plan.json`：完整依赖计划；
- `workspace/units/*.json`：360 个工作单元；
- `workspace/receipts/*.json`：360 个边界校验收据；
- `workspace/interface_registry.json`：单元路径、依赖和哈希注册表。

## 3. 首次执行

```powershell
python -m orbit360 run --workspace workspace --workers 8
```

首次执行应显示：

```text
executed_count = 360
reused_count = 0
formal_evidence_status = NOT_EVALUATED
```

## 4. 验证续跑

再次执行相同命令：

```powershell
python -m orbit360 run --workspace workspace --workers 8
```

预期：

```text
executed_count = 0
reused_count = 360
```

## 5. 验证局部修复

```powershell
python -m orbit360 repair --workspace workspace --target unit_008 --delta 1
python -m orbit360 run --workspace workspace --workers 8
```

默认宽度 35 下，`unit_008` 的受影响闭包为 11 个单元。修复后的运行应执行 11 个、复用 349 个。

## 6. 查看状态

```powershell
python -m orbit360 status --workspace workspace
```

所有命令默认输出 JSON，便于自动测试或其他工具读取。

## 自定义小规模场景

```powershell
python -m orbit360 plan --workspace workspace-small --units 40 --width 8
python -m orbit360 run --workspace workspace-small --workers 4
```

`--units` 范围为 1–5000，`--width` 范围为 1–256，`--workers` 范围为 1–32。项目不接收任意命令参数，也不会执行单元文件中的代码。

## 清理

`workspace/` 是本项目的可再生运行输出，已被 Git 忽略。需要重新开始时可在确认路径后删除该目录，再运行 `plan`。不要把该工作区当作 CGKN 正式交付证据。
