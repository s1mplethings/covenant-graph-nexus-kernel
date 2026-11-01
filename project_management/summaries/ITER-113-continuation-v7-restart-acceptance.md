# ITER-113 v7：CGNK 自行补齐真实进程重开测试

本次指定工作已完成：CGNK 自己修改并执行真实进程重开测试，冻结后独立复跑 **15 passed（30.46 秒）**，有效的数据丢失变体被该测试拒绝。宿主未修改候选业务代码或测试。完整产品仍不能宣称自主达标：交接尚未完成，工程观察评分 78.4375，领域质量真人审查待完成。

## 实际执行与资源

在同一连续 DEV 链上，从 80 次累计请求继续到 123 次，没有清零旧账。新配置将请求上限提高到 2,000，保留 600 万 token、3,600 秒开发时间及原费用约束。累计 token 含未知预留为 1,669,480，累计有效开发时间 1,179.81 秒。

本次新增 43 次请求，保守费用 **11.11146 元**；余额 **63.18924 元**。历史累计账本 124.80006 元，上限仍为 187.98930 元。供应商实际账单未查询；失败和未知调用继续保留费用上界。独立验收零付费调用。

使用既有 DeepSeek/Grok 路由，无新增强模型救援。开发后段 Grok 返回 `SSL: UNEXPECTED_EOF_WHILE_READING`，有限切换后 DeepSeek 返回 `WinError 10060`，原始终止原因 `PROVIDER_TRANSPORT_FAILED`。不是请求、token 或费用耗尽。新候选已正常冻结，验收不受 API 中断影响并已完成。

真实入口：`python -X utf8 -m experiments.product_dev_113.run_dev --execute --stage 6 --freeze freeze-v7.json --authorization F:/CGKN-ITER-113/continuation-v7/authorization.json --feedback F:/CGKN-ITER-113/continuation-v7/public-feedback.json`。这是已执行历史命令，重复调用会拒绝覆盖现有阶段。

## 测试真实性和独立验收

模型修改了 `test_app.py` 和 `app.py`。新增测试通过 `subprocess.Popen` 启动真实 Flask 应用，在临时数据目录通过 HTTP 上传素材和导出，终止首个进程并确认退出；再启动新进程，检查素材可见、下载、导出文件、数据库记录和搜索接口，最后终止第二个进程。测试还加强了导出时长断言。

独立负向验证在专用隔离副本中，于第二个进程启动前移除该测试自己的临时数据，记录触发前数据库确实存在、两次应用进程启动；原测试在“重开后素材仍可见”断言处失败。没有修改测试断言或原候选。这证明测试可以识别重开数据丢失，不是只检查进程启动或返回码。

测试使用合成媒体；对转录仅检查表可读，对原文件只检查下载长度。因此不把这一个测试解释为所有真实 ASR/媒体历史都已覆盖。另行独立 GUI/真实媒体验收确认了应用及浏览器重启前后数据库、文件和 HTTP 下载哈希一致。

回归结果：

- 正常副本：15 passed。
- 错误来源、错误时长、不可解码输出：分别 3 failed / 12 passed；三个失败是受输出破坏影响的导出和重开测试，注入产物均有独立检查记录。
- ASR 执行失败和解析失败均有实际注入命中，失败素材转录数为 0、状态正确；恢复真实依赖后新素材转录成功，原失败记录保留。
- GUI 新素材导入、真实 ASR、检索、导出、非法边界及重开复验已执行。指定 alternate.mp4 的 7–12.5 秒导出独立解码及来源画面/声音对齐通过：三帧 MAE 0.965/0.791/0.773，声音包络相关性 0.999991。
- 模型另改了导出 GUI 下载入口。独立验收按实际页面选择器操作，没有为其补业务代码。

候选带有模型开发期间导入的 scenario.mp4。首轮通用 GUI 选择器选到了旧素材，原轨迹保留；随后明确选择新 alternate.mp4，做一次对象选择复核和独立媒体检查。不能把首轮旧素材结果冒充新素材验证。

## 结论范围

指定的“模型自行补齐并执行真实进程重开测试”已 PASS。完整产品观察评分及 24 项理由见 `continuation-v7/quality.json`：78.4375，D 均值 3；不归一化，也不以宿主测试代替模型测试。README 和 PROJECT_STATE 仍未完成更新；完整原题包最终逐项审查未全部重做，领域质量保持 PENDING_HUMAN。故不计自主完整交付。

正式矩阵仍为 0 启动、0 完成、32 个 NOT_RUN；没有新增 Direct 对照，不能据此宣称架构优势。这是已公开反馈后的同一工程 DEV 续作，不是新盲测样本。

## 保存与恢复

- 冻结候选：`F:/CGKN-ITER-113/dev-stage-06/frozen/candidate.zip`
- 原始模型/工具/审计：`F:/CGKN-ITER-113/dev-stage-06/`
- 新授权和配置：`continuation-v7/authorization.json`、`packet-v1/freeze-v7.json`
- 独立证据：`acceptance-v7/`、`mutations-v7/`、`restart-negative-v7/`、`asr-exit-v7/`、`asr-parse-v7/`
- 汇总/评分/干预/Corpus 回执及新封板：`F:/CGKN-ITER-113/continuation-v7/`

旧 v6 封板 401 个文件复核无变化；框架回归 19 passed，新增累计上限/失败预留离线回归 1 passed。仅修改通用请求限额接线，未修改隔离政策或产品架构。所有候选修改来自模型工具动作；验收结果未回流给已终止开发 Agent。

当前指定测试无需继续付费。若继续完整交付，现存外部阻塞是 Provider 传输可用性，剩余预算无需重新授权；恢复时新建追加阶段和配置版本、继承累计账目与 stage 06 候选，不重用旧目录。当前候选可在既有冻结镜像中零费用复验，准确工具入口为 `experiments/product_eval_076_v8/inspect_candidate.py`（新 `--root`，`setup --snapshot ... --public ... --argv '["python","/workspace/app.py"]'）。
