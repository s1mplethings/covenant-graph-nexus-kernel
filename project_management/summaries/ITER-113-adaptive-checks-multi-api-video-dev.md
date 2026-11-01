# ITER-113：自适应检查、多 API 与视频项目续作

正常视频业务链可以使用，但**尚未完整达标，NOT_DELIVERABLE，PENDING_HUMAN**。新实例的 GUI 导入、真实 ASR、检索定位播放、实际导出、下载、重开和普通归档均有本轮证据。执行失败已不再伪装成 ASR completed；但执行失败与解析失败的原因仍丢失，自有测试仍缺少真实进程重开验证，并漏检同样时长的错误来源媒体。

CGNK 完成了已公开问题的业务修复，没有证据表明本轮自主发现了新的业务缺陷。新的错误来源测试漏检由外部验收发现。内部 Observer 只完成无模型通路验证，本轮真实开发没有调用它。不能把预设检查、外部发现或收到反馈后的修复写成新的自主发现。

三家 API 均有真实返回。Qwen 主要进行项目读取；DeepSeek 承担后续协调、需求检查映射和实际业务补丁；Grok 接手过协调观察，随后传输失败，原任务状态被交还 DeepSeek。没有真实并发，也不能据此证明多模型导致质量提升。

新增保守费用 **20.79718 / 100 元**，本次新额度剩余 **79.20282 元**。历史累计 **108.78648 / 187.98930 元**。这是保守上界账目，不是已查询的厂商账单。5 次未知用量均保留预留，未释放旧费用制造余额。开发停止于下一请求无法通过共享 token 上界准入，不是验收费用预留或 API 费用耗尽。

## 起点与版本

- 当前 HEAD：`0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`；分支 `codex/provider-gateway-integration-20261017`。
- 仓库既有报告占用到 ITER-112，本轮使用新的 ITER-113；没有覆盖 ITER-090 或当前已关闭的 ITER-015 管理快照。
- 起点是 `F:/CGKN-ITER-090/dev-stage-04/frozen/candidate.zip`，没有从空项目重建，没有引入 Direct。
- 本轮一个连续工程 DEV 链、4 个阶段、1 个产生业务修改的候选。不是 4 个独立样本。正式实验 0 次，旧 32 格未重跑。
- 最终候选：`F:/CGKN-ITER-113/dev-stage-04/frozen/candidate.zip`；原样展开：`F:/CGKN-ITER-113/deliverable/project/`。
- 全部新证据：`F:/CGKN-ITER-113/`；详细账目、逐项评分、义务与干预：`closeout/`。
- 旧 ITER-090 封板的 971 个文件逐个校验，全部未变。

## 实际产品验收

| 业务责任 | 本轮独立观察 |
|---|---|
| 新真实媒体 | 从原授权 JFK 素材公开片段派生 20 秒新输入；来源及哈希事前保存 |
| GUI 导入与 ASR | 实际 whisper 运行，转录关联正确素材；非预制答案 |
| 检索与播放 | `permit` 命中该素材 9.42 秒；一次浏览器 userGesture 操作复核后实际播放，观察到 10.013 秒且 paused=false |
| GUI 导出 | 选择 7–12.5 秒，实际输出 5.505506 秒；符合原 1 秒容差 |
| 来源和产物 | ffmpeg 独立解码成功；三个来源画面对照 MAE 均小于 1；音频包络相关 0.99999057；HTTP 下载与保存文件哈希一致 |
| 输入边界 | 负起点、相等、反向、超长、坏视频、空文件均拒绝；已有成功数据保留 |
| 普通归档 | 同名普通文件通过 GUI 上传两次，身份和路径不同；下载内容均与原输入一致；原有 note 保留 |
| 重开 | 真正重启应用和浏览器；记录、文件哈希、下载字节一致，GUI 可以再次检索 |
| 无音轨 | GUI 显示 no audio track，不伪装转录完成 |
| ASR 非零退出 | 有实际注入标记和对应 WAV 参数，GUI/数据库为 failed，转录 0 条；恢复依赖后新导入成功 |
| ASR 坏 JSON | 同样实际命中，failed、0 转录；恢复后成功。但两种错误都没有保留原因或可区分的用户状态 |
| 自有测试 | 最终 14 passed，23.10 秒；测试文件与 ITER-090 相同，未应用新的测试补丁 |

正常 GUI 轨迹 54 次操作，在公开 60 次上限内。播放第一次脚本点击受到浏览器用户手势策略限制；一次真实 userGesture 复核保留了前后两次轨迹，没有改代码。自动 GUI 操作不代表真人可用性审查。页面导出/错误反馈仍直接显示 JSON，已在体验评分中体现。

`acceptance-v1/` 为正常轨迹；`asr-exit-v2/`、`asr-parse-v2/` 为有效故障和恢复轨迹。正常空转录分支未单独作独立验收，不补成 PASS。

## 检错效果与发现归因

正常 14 项测试首先通过，再在独立副本中施加错误变体，原候选未改：

| 有效变体 | 自有测试结果 | 结论 |
|---|---|---|
| 请求 1 秒，得到 6.128 秒可解码音视频 | 2 failed、12 passed；返回 500 导致对应成功路径断言失败 | 新增业务时长保护使这项已知回归被拒绝；不是新测试带来的收益 |
| 不可解码产物 | 2 failed、12 passed；对应导出断言失败 | 保留已有检错能力 |
| 正确 1 秒长度，画面替换成红色、音轨替换成另一声音 | **14 passed** | 有效漏检；独立对照来源画面 MAE 130.780，大于事前阈值 20 |

第三项另外复核了两个导出测试与原始素材的逐帧差异，两项仍 PASS。不是依赖失败、语法错误或未触发场景。它证明自有测试缺口，不证明正常导出总是选错来源。

已知时长/ASR 状态问题的业务补丁来自 DeepSeek 的原始 worker call-047。call-064 提出了新增测试，但只返回了四个 envelope 字段，缺少契约要求字段，因此被拒绝，未应用。宿主没有补字段或补测试。需求映射由模型写入 PROJECT_STATE.md，但后续没有及时更新，保留其过时状态。

最初两份本轮 ASR 包装程序注入没有命中，保留为 EVALUATOR_INVALID。诊断证明 `/tmp` 是 `noexec`，`os.access(..., X_OK)` 为 false，直接执行得到 PermissionError，启动日志的 which 实际选择 `/usr/bin/whisper-cli`。新版把包装程序放入本副本可执行工作区，并在启动前断言解析路径；GUI 上传后有真实命中标记。仅修验证器，不修改原候选。历史无效检查仍是无效检查，不能追溯改写成有效失败。

## 框架修改与边界

沿用原 AgentProjectLoop、CapabilityTree、compile_tree、DAGRunner、ExecutorRegistry 和 FileRunStore。没有启用 dormant Architecture Router，没有另造计划器或固定 QA 阶段。

1. ActionComposer 支持受注册表约束的协调模型切换，保留目标、树、原始结果及共同预算。
2. LLMExecutor 使用请求级不可变 Provider 配置，Agent 可以给节点选择不同 Provider。
3. 模型自己维护的 PROJECT_STATE.md 和完整原始结果索引进入后续请求。长输出机械分页；最近两条保留完整窗口，其他记录保留引用和哈希。宿主不生成业务摘要。
4. 可选 Observer 使用独立容器及一次性候选副本，工具结果返回原 DAG；没有业务修改合并权限，没有最终验收材料。验证记录区分执行有效性、代理结论、版本与条件。
5. Provider 接入复用 API Lab 的凭据解析和 Chat Completions 适配。当前是结构化 JSON 动作协议，不宣称已测试原生 tool-call ID、Responses 或图像输入。厂商远程搜索/工具关闭。
6. 共享账本在发送前预留；未知用量立即占用本轮资源。Grok 推理用量按返回总量归一，避免已包含的 reasoning 重复累计。失败切换不重放工具动作。
7. 由于旧取证适配使用进程级拦截，本轮串行锁住准入、传输、结算。两提交者竞争检查证明不会超发；没有声称支持真实并发写入或真实并发 API 请求。

版本顺序：v1 首次通路；v2 调整输出反馈、Qwen 故障后换配置；v3 明确暂停重复读取后修复反馈窗口；v4 实际验证 Grok→DeepSeek 传输切换。每阶段原始请求、候选、费用均保留。

最终 v5 **仅离线验证**：精确重复观察绑定源代码/测试/数据库内容哈希；变更后旧阻断失效；第三次不变观察阻断该动作，其他动作仍可继续。真实模型运行用的是 v4，不能把 v5 测试写成又做过付费开发。语义等价但字节不同的停滞仍依赖 Agent 判断；没有用宿主业务分析替它解决。

完整宿主干预见 `closeout/interventions.json`。阶段 2 有一次外部进程暂停，在途请求结果未知、费用保留，另存进程身份和冻结收据。不是零干预首次成功。未向开发者回流本轮私有验收结果，未由宿主修业务代码/测试/数据库。

## API、成本与终止

| Provider | 请求 | 可核验 usage | 未知 usage | 保守费用（元） | 实际作用 |
|---|---:|---:|---:|---:|---|
| Qwen / qwen3.8-max | 9 | 7 | 2 | 5.27710 | 项目读取；连续连接故障后停用 |
| DeepSeek / deepseek-flash | 46 | 45 | 1 | 11.58460 | 协调、需求映射、业务补丁、基线测试安排；测试补丁无效 |
| Grok / grok-4.7 | 10 | 8 | 2 | 3.93548 | 续接协调和观察；重复观察切换后实际接手，SSL EOF 后回交 DeepSeek |

合计 65 次：61 次协调请求、4 次 worker 请求。含未知预留的 token 为 959,867；开发墙钟保守累计 509.77 秒。下一请求的输入加输出上界无法放入 1,000,000 token 额度，发送前停止。未偷偷增加请求/token 上限或释放未知费用。独立验收、离线回归和归档新增 API 调用 0。

计价依据和官方核对链接存于 `price-sources.json`；采用统一输入 20 / 输出 60 元每百万 token 的保守上界，美元转换保守上界 10，未享受缓存折扣。Grok 输入限定在较低上下文计费范围。返回模型与请求别名逐条分开保存。

## 质量、回归与交付

24 项工程评分完整记录在 `closeout/quality.json`：**71.5625/100**，未归一化；D 均值 2，未达到 3。G3 失败，G6 部分完成。领域 Q1–Q4 未作真人评审，保持未知；不填零，不声称最终达标。正常产品有用与完整质量达标分别判断。

- 最终相关回归：19 passed，0 skipped；前序测试自身的失败也保存。
- 真实 runner 无模型 conformance：PASS，包括成功反馈、Worker 读写、非法动作、失败关闭；v5 复核通过。
- Observer 独立副本 conformance：PASS，探针修改没有进入原候选；不是模型产品成绩。
- 原工作树方向检查 FAIL，775 项历史错误保留，没有删目录或放宽规则。
- 最终当前源码快照：全部 git 跟踪文件的工作树内容加本轮显式活动源码，在新目录运行同一个 product_direction_gate.py，PASS。快照清单保存；这与原工作树历史目录检查分别报告，不冒称全仓清洁。
- 没有运行全量 pytest，没有推送、合并、发布或公开宣传。

现有 Project Corpus 追加框架、最终候选和连续 DEV 链记录，使用原 schema、对象存储和索引；收据与逐条校验见 `closeout/corpus-receipts.json`。阶段记录不重复计样本。私有媒体、错误变体和原始日志不提交公开仓库。

在声明镜像内，候选仍按模型 README 运行 `python app.py`。用户宿主预览代理此前被自动审批拒绝；本轮没有换代理或端口绕过，未声称宿主地址已经可访问。可直接执行以下零费用入口，在一个尚不存在的新目录中重新启动隔离验收副本：

```powershell
cd D:/CGKN
python experiments/product_eval_076_v8/inspect_candidate.py --root F:/CGKN-ITER-113/review-copy-01 setup --snapshot F:/CGKN-ITER-113/dev-stage-04/frozen/candidate.zip --public F:/CGKN-ITER-113/acceptance-inputs --argv '["python","/workspace/app.py"]'
python experiments/product_eval_076_v8/inspection_action.py --root F:/CGKN-ITER-113/review-copy-01 --url http://127.0.0.1:5000 --screenshot home.png
python experiments/product_eval_076_v8/inspect_candidate.py --root F:/CGKN-ITER-113/review-copy-01 command --argv '["python","-m","pytest","test_app.py","-v","-p","no:cacheprovider"]'
python experiments/product_eval_076_v8/inspect_candidate.py --root F:/CGKN-ITER-113/review-copy-01 close
```

本阶段付费运行已经关闭，不能用新 run ID 重置技术额度。若续作，应沿用同一候选、保留本账本，明确调整 token 技术上限；未使用的 79.20282 元仍保留，不需要误报为费用不足。将本轮私有失败用于修复时，应另存明确的公开反馈版本，后续只算暴露后的回归。

本轮观察支持“已公开时长和 ASR 假成功问题得到模型修复并有运行证据”，不支持“完整项目自主达标”“内部交叉验证已有效发现未知问题”或“多 API 导致提升”。
