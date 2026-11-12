# ITER-115：目标阶段机制、真实维护与异构验证

2026-10-28。当前结果：部分完成，真实网络阻塞，原视频项目真人领域评审待完成。没有把基础设施、内部代理判断或预约小任务当作完整视频项目交付。

## A—E 结果

|范围|实际结果|证据|
|---|---|---|
|A 通用机制|接入现有 AgentProjectLoop、Tree/DAG、ExecutorRegistry、FileRunStore；相关回归 80 passed；仍有下述实现限制|F:/CGKN-ITER-115/regression-final-v9.txt；final-route-conformance/result.json|
|B 两种机制夹具|真实 HTTP/SQLite 预约与异步投递，正常/错误对象/并发/版本/重复等反例及实际页面操作通过；宿主编写的合成测试|tests/agent/test_goal_domains.py；fixture-gui-results.json|
|C S09 真实修复|CGNK Worker 修改自有 GUI 测试和说明；正常上传通过，未保存与下游旧对象变体均被拒绝；23 pytest 通过|acceptance-stage16-assessment.json；acceptance-stage16-*/；video-independent-stage16/|
|D 预约真实任务|从仅 requirements.txt 的中性起点由 CGNK 规划、实现、修复和检查；8 条公开要求在限定纵向范围通过独立验收|reservation-acceptance01/final-assessment.json|
|E 原视频完整交付|UNVERIFIED / PENDING_HUMAN。工程80.00、D均值3.00；CGNK内部还缺search/export/retry目标检查，网络阻塞|quality-stage16.json；video-stage-view-final.html|

旧 stage09 工程78.75/D2.75 保留。新评分只绑定 stage16；app.py 与 stage09 相同（SHA256 683a2600cbd0254433c8c952f594cec9ef55b5f6677293d9a7410f5f11fc3457），无关业务证据按此依据复用；自有测试、当前上传/导出/重开重新验证。领域 Q1—Q4 没有代填，未归一化。真人材料：F:/CGKN-ITER-115/human-review/index.html。

## 通用接入与实际边界

- GoalAcceptance 追加计划和检查历史，目标关联公开要求、对象身份、条件、注册检查器和当前存储回执。执行成功不自动验收；生产者自写 VERIFIED 不生效。
- ActionComposer 的 plan 驱动原有规划循环；无新规划器或调度器。主规划收到当前目标差距、原始工具结果、有效策略与历史反馈适用范围。
- 连续模式把决策次数改为检查点，保存 Tree、原始结果引用、目标、尝试和账目。未知中断副作用不自动重放；由模型决定检查/重试。
- 仅本轮授权采用 accounting_only；旧限额模式保持。单请求超时、有限重试、隔离和实际账号权限继续有效。
- 主规划与Worker分别配置，适合主规划的授权替代为Qwen/Grok；没有静默使用Worker默认值代替主规划。角色按真实schema/请求/返回身份审计。
- 检查器使用隔离副本，私有外部验收不进入开发/Observer；新增检查防止修改原业务源码后对原候选报通过。当前真实Observer副本的回溯核验未发现原源码改动。
- 按实际记录生成阶段表和依赖图；相对顺序不伪造日期。预约第三个空目标阶段显示 NOT_REQUIRED，而非虚构已验收阶段。

新增/主要修改：cgkn/state/acceptance.py、cgkn/agent/composer.py、action_composer.py、project_loop.py、cgkn/runtime/dag_runner.py、scripts/provider_api_budget.py、experiments/product_dev_113/{routes,runner,run_dev,run_task,goal_check,observer,live_provider,budget_policy,network_client,paths,recover_interrupted}.py、scripts/render_goal_progress.py、相关测试和 docs/goal_acceptance.md。

不是所有设计要求都已充分证明：真实运行只接受过一个业务计划版本，动态拆分/重排在离线生产入口验证，不能声称真实多轮业务阶段重构已发生；真实生产节点串行，离线 barrier 证明了可选并行执行；当前对象绑定保守采用整体源码/测试/数据库身份，细粒度证据复用尚未完整接入。早期v1—v4有封板哈希但缺完整源码档案；v5—v9完整源码副本保留。架构门禁仍FAIL于预存 benchmarks/orbit_360_workbench 与 benchmarks/project_generation_v1，未擅自删除用户目录。

## 真正规划—执行—差距—重决策

预约 call491 Qwen读取输入；call493计划进入Tree/DAG；call494 Worker委派；传输失败后call497显式切Grok，call498重委派；语法失败由模型再次委派修复；call506检查揭示并发测试缺口，call515委派增加并发测试，call518实跑，call519/523/543复验，call549在目标证据有效后结束。详见 planning-trace-reservation.json 与原始provider目录。没有宿主业务补丁。

视频修复连续经历6次宿主通用框架恢复，分别记录在 framework-recoveries-through-stage15.json。stage13外部反例仍假成功；stage15开始拒绝坏输入但也误拒绝正常输入；stage16修正后正常与两个有效反例均通过。公开反馈只披露业务观察，具体私有注入实现未回流。这是反馈驱动修复，不是未见问题的首次自主发现。

内部 GOALS_VERIFIED 仅表示已配置的代理目标通过，不代表外部验收或人类领域判断。预约冻结后独立操作者完成GUI预约/冲突/指定取消/重新预约，7个同步竞争请求1成功6冲突，实际重启后DB与页面身份一致；自有7测试全过且拒绝两个语法有效业务变体。候选SHA256 a0618e16f53f89fbc90f84fe3ab7676a81e5f1c9ef49e217979428235a287533。

视频最终候选SHA256 141ad46b3d035660687acf0e7eab915ab08f5819a937e9c5b2cc8d352ee5f844。独立GUI选当前alternate.mp4，检索permit、定位、7–12.5秒导出与进程重开通过；导出独立解码通过，音频相关约0.999946，能量对齐约0.999991，图像差异检查通过。不能据此代替真人语义/可用性评分。

## 真实调用与费用

本授权新增尝试420次：主规划152、Worker33、Observer235（含失败/重试）。实际成功返回模型为qwen3.8-max、grok-4.7、deepseek-flash；未确认返回的失败单列，不用请求名冒充实际模型。已知响应token6,394,868；33次缺少完整usage或结果，预留保留，不伪造为零。

历史累计186.70886元；本授权新增保守195.94132元；全链保守382.65018元。真实账单和供应商余额未查询。无应用内金额停止门槛。并发分支继承计数不能直接相加，统计按逐条调用身份；完整表 call-audit-final-v2.json。费用是既有保守计费规则，不声称与实际账单相同。宿主框架和本地计算不是“完全零成本”。

旧32格未重启；本轮新正式比较0次。阶段10—16是同一视频维护链的执行版本，不是7个独立项目；另有1个真实预约纵向任务。

## 当前硬阻塞与恢复

stage16在Grok、Qwen各有限尝试均ConnectError后自动封板。NET114端口在监听、WLAN Up；重启原专用代理（PID51240→38748，同冻结配置哈希）后，DeepSeek/Grok探针仍TLS失败；Qwen主/备路由探针也失败。后续继续复查仍失败。没有改日常VPN、购买服务、增加权限或降级TLS。有限恢复原始记录：network-*-stage16.json、network-qwen-after-restart.json、network-continue-check.json、network-proxy-recovery.json。

先恢复既有专用线路，使授权Provider至少一条主规划路线可用，再执行：

```powershell
powershell -NoProfile -File F:/CGKN-ITER-115/recover-stage17.ps1
```

stage17仅LOCAL_CONFIG_VALID，未启动。脚本保留stage16候选、状态、账目并使用v9，拒绝覆盖已有stage17。若路径已存在应先检查记录并分配下一个未使用编号。真人领域评审是另一个独立待办，不需为常规续跑重新批准费用。

查看阶段：

```powershell
python scripts/render_goal_progress.py --run-dir F:/CGKN-ITER-113/dev-stage-16/run/cgkn-state/product-eval076/dev113-cgnk-stage-10 --output F:/CGKN-ITER-115/video-stage-view-refreshed.html
```

测试：`python -m pytest tests/agent tests/runtime/test_dag_runner.py tests/test_provider_api_budget.py experiments/product_dev_113/test_network.py experiments/product_dev_113/test_transport.py experiments/product_dev_113/test_continuation_limits.py -q --run-profile-marked`。本轮最终80 passed，不冒称全仓全量回归。

回滚不自动覆盖脏工作区：本轮前备份位于 baseline，冻结源码位于source-v5至source-v9；需要回滚时逐文件核对当前哈希与相应封板后恢复，不能批量reset。候选/原证据从未覆盖，stage09原ZIP哈希仍为f4a6b262ee8ceb1d8639d4682f79f7b38103a89bbdf9cbd2bcc2bc6affc8f583。

Corpus使用既有 F:/CGKN-ITER-060/project-corpus；条目回执见 F:/CGKN-ITER-115/corpus。没有推送、合并或发布，没有宿主候选业务修复。私有验收原始数据保留本地，不放入公开仓库。临时开发/检查容器已结束；原先不属于本轮的检查容器和NET114专用代理保留。

## 最后环境复核追加

最终执行 `docker ps` 时 Docker Desktop Linux engine 管道已不存在，无法再次确认全局容器状态。此前逐个 close/封板回执仍有效；不把当前清理状态冒称已复核。恢复 stage17 还需 Docker Desktop Linux engine 可用。原始错误见 F:/CGKN-ITER-115/final-environment-blocker.json。此项是在上述Corpus条目之后追加，另行保留追加记录。
