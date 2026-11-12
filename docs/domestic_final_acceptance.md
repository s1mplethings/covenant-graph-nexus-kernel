# 国内模式最终收口验收

本轮复用国内直连、Gateway、AgentComposer、DAGRunner、FileRunStore、现有预算及响应缓存，没有重新开发代理、Watchdog、熔断、fallback、DNS 或出站绑定机制。

## 当前状态与付费边界

本轮真实模型生成尚未获得明确金额授权，实际生成调用为 0，真实 CGKN 任务保持 BLOCKED。网络与认证通过不能替代真实生成/任务验收。

已封存并经独立端复核的最小运行包：

`D:/CGKN/artifacts/domestic-final-20261028/prepared-run-v3/plan.json`

正常最多三次调用：Qwen 规划 → DeepSeek Worker 修复原始 a-b 加法函数 → 在新进程中重开同一任务后 Qwen 收尾。使用原 AgentProjectLoop continuous 检查点，不新增规划/调度/任务状态系统。

每次上游请求不超过 16000 字节（按 16000 输入 token 保守预留）；Qwen 每次输出最多 1200 token，DeepSeek 最多 512，关闭 thinking；最多 2 次 planning、1 次 generation。已核验官方单价下的上界估算约 0.506496 元，保守统一输入/输出 20/60 元每百万 token 预留上界为 1.13472 元。建议本轮授权金额上限 2 元，最多 3 次调用，不追加修复轮次或未知提交重发。账单未查询，不能把预算预留当实际账单。

授权模板 `authorization-request.json` 的 approved=false，金额为空。必须先收到用户明确授权，再按实际授权保存引用及金额；不得自行把模板改成批准。

## 授权后的执行入口

以下仅为已批准后的命令，不是授权本身。v1/v2 旧准备包保留为历史，源码变化后会失败关闭，不得使用。

```powershell
cd D:/CGKN
$run = 'D:/CGKN/artifacts/domestic-final-20261028/prepared-run-v3'
# 仅在收到本次用户授权、保存正确授权文件后执行。
python -X utf8 -m scripts.domestic_task_acceptance execute --root $run --authorization '<本次已批准授权文件>'
# execute 在原 runtime 已保存 next_decision=2 检查点后停止，未发送第二次 Qwen 请求。
# 新 Python 进程重开相同 run_id、goal、schema、模型限制和独立账本。
python -X utf8 -m scripts.domestic_task_acceptance finish --root $run --authorization '<同一授权文件>'
# 下面两步不产生生成费用。
python -X utf8 -m scripts.domestic_task_acceptance verify --root $run --oracle D:/CGKN/artifacts/domestic-final-20261028/independent-review/verify_add.py
python -X utf8 -m scripts.domestic_task_acceptance reopen --root $run
```

execute 前必须是未修改的原始失败项目；baseline、源码、外部 Lab 执行依赖、Provider 公共配置身份及独立 oracle 都有哈希约束。规划只能提交 inspect/fix/test 三节点及指定配置；最终决策只能 finish，不能额外执行工作。Worker 只可改 math_utils.py，在 pytest 前先检查纯函数 AST，禁止 imports/calls/attributes/副作用；该安全检查允许 a-b、常量 5 等错误实现，不充当语义成功判断。

## 独立结果门槛

独立验收端生成并封存了 verify_add.py；新 Python `-I -S` 进程执行 135 个固定边界、大整数、随机输入，独立比较 a+b，核验原测试及其他 fixture 文件未变。仅返回常量 5 虽可骗过原始单项 pytest，独立 oracle 会拒绝。

最终真实任务 PASS 还必须同时具备：task-result=SUCCEEDED；同一 run/账本内三次真实模型调用；Qwen/DeepSeek 上游响应实际 model/id/usage 与哈希证据；独立 oracle PASS；重开 DAG 的 attempts 不增加且无新模型调用。实现者的 pytest 或 Agent finish 均不能单独宣布成功。合成回归只证明运行包机制，不等于 L4。

## 未知提交与成功结果丢失窗口

现有 canonical provider_api_budget 保留 INTERRUPTED_UNKNOWN，拒绝相同 request_identity 的再次提交。迟到 usage 可结算费用，但不能清除未知提交锁存。已成功、尚未写入 Agent 决策/Worker 结果的响应，通过原身份绑定缓存重建；缓存 replay 的 attempts=0，不假装发生了新的 Provider 调用，也不假装旧费用为零。

已用真实本地 HTTP POST、客户端超时、第二个 Python 进程验证：服务端收到一次后，相同请求被预算层拒绝，计数仍为 1；成功缓存也能跨进程恢复。保证范围是固定输入/identity 与同一账本，不能泛称所有请求普遍 exactly-once。

## 稳定网卡身份与 Gateway

国内 route 增加 interface_guid；原 ifIndex14 和 192.168.1.100 仅是上次观测值。启动时按 GUID 查询当前物理网卡、Preferred IPv4 和索引，要求唯一、HardwareInterface=true、Status=Up。断开、身份缺失、多地址或非物理接口均安全拒绝。

运行中每次请求前重新核验 GUID；若当前索引/源地址与已建池不同，先拒绝请求，要求明确重启 Gateway，避免在进行中的未知请求上热切换/关闭连接池。重启后重新解析 GUID；不回退到 VPN 或默认接口。

已实测正常停止/启动、旧 session 删除及新私密 session 建立，338 个任务状态文件哈希不变；当前 /models 非生成认证两家均 200。索引/DHCP 变化及断开路径用隔离快照测试；没有真的断开 WLAN 或续租 DHCP，避免影响日常网络。真实缺失 GUID 的只读 Windows 查询已验证启动拒绝、Provider 请求 0。

GUID 查询当前有数秒开销；这是接口核验时间，不能误报为 Provider 网络延迟。更换物理网卡导致 GUID 变化时须明确核验新身份，不能自动猜测另一网卡。

## 隔离取证与限制

目前保留 Windows socket/指定 WLAN 出站证据，物理包级独立证明仍 NOT_VERIFIED。管理员受限抓包授权尚未收到，没有抓包、提权、关闭日常 VPN或修改全局路由/DNS/防火墙。

拟定范围仅为两个官方 API 目标的 IPv4 TCP 建连头、最长 15 秒，不解密、不记录应用正文。自动审批拒绝了保存包含具体抓包操作命令的计划（blocked by policy），未执行相关命令，也未改写命令绕过拒绝；仅保存范围说明。

Docker 默认 bridge 仍走 TUN 的历史反例保留。当前生产 Provider 在 Windows Gateway，无需为此重做 Docker 网络。Grok 继续可选 DISABLED，不影响国内模式验收。

## 审核、回归、回滚

完整报告与逐项证据：`D:/CGKN/artifacts/domestic-final-20261028/report.md`。补丁以本轮开始时的真实工作区为基线生成，不混入已有未提交工作；没有 staging/commit/push。精确文件哈希及回滚清单也保存在同目录。

回滚前停止国内 Gateway，并确认没有尚未核对的真实 unknown 请求；不能通过回滚预算保护来重发未知调用。默认只校验：

```powershell
python -X utf8 -m scripts.domestic_network rollback --manifest D:/CGKN/artifacts/domestic-final-20261028/rollback-manifest.json
```

显式 --apply 才恢复本轮既有文件备份；不清数据库、不删除任务状态、不硬重置仓库。新增工具保留但不自动加载。源码变化后已封存运行包会拒绝执行，需重新准备并独立复核。
