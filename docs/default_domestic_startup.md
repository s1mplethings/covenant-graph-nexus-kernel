# CGKN 默认国内 Gateway：启动、预算接线与恢复

2026-10-28 当前说明；本轮报告为 artifacts/domestic-fix-20261028/report.md。之前GET-only、导入时启动、旧POST始终阻断及手工清理遗留session的说明已经被本轮修复替代。

## 正常使用

原Codex CGKN插件启动命令不变：D:\anaconda\python.exe ./scripts/cgkn_mcp_server.py --cgkn-root D:\CGKN，工作目录仍是已安装插件目录。重启一次修改前已加载旧模块的插件/应用连接后，照原方式使用即可；无需手工设置CGKN_NETWORK_MODE或另选国内模型配置。没有修改缓存插件、系统/用户全局代理、路由、DNS、防火墙或日常VPN。

保存的 .cgkn/agent-kit.json 指向 config/domestic_application.json：模式、模型角色、网络配置、接口GUID、Gateway运行时和状态目录一起加载。覆盖profile的相对路径按CGKN仓库根解析成绝对路径，在启动进程中继承给子进程，不随worker cwd漂移。

MCP导入及initialize不再连接或启动Gateway；本地doctor/status、取消和适用离线功能仍可加载。doctor返回结构化应用网络状态：CONFIG_ERROR、UNAVAILABLE及具体原因，或OS进程状态。ALIVE表示进程身份存在，不替代上游HTTP/认证/生成验收。首次真正需要网络的调用才强校验并按配置启动/恢复Gateway；失败不会退回旧API客户端或代理。

路线：原插件/worker -> 预算GatewayCompletionClient -> Windows loopback Gateway -> Qwen/DeepSeek独立HTTP池 -> 保存GUID对应的WLAN socket。当前GUID31fde520-1fc1-4a43-a5a9-8ca730ff5821，当前源192.168.1.100/index14。地址与索引仍由GUID核验，不能把这些观测值当永久身份。国内不使用17890/17891，Grok可选禁用。

## 查看选路

新插件cgkn_doctor的report.application_network提供本地状态/错误；cgkn_probe_provider + RUN_PROVIDER_PROBE在国内模式只执行两家固定GET /models，不执行生成。查看公有文件：

```powershell
Get-Content D:\CGKN\config\domestic_application.json
Get-Content D:\CGKN\.cgkn\domestic-gateway\status.json
Get-Content D:\CGKN\.cgkn\domestic-gateway\application-startup.jsonl -Tail 5
Get-Content D:\CGKN\.cgkn\domestic-gateway\last-route-probe.json
```

不要打印或上传session.json：它含本地Gateway访问令牌。启动日志轮转，无供应商密钥。上游诊断分别记录gateway_http_status、upstream_http_status、解析/模型是否列出、ok和原因。201不会伪装200通过，错误/模型缺失/坏JSON不会算PASS；只保留响应字节数及摘要。

## 正式生成接线

原generation_command -> run_codex_conversation_generation.py -> codex_conversation.run_formal_generation_once -> 原Provider边界保持不变。run_local_pipeline_impl.provider_text在surrogate处理后、旧local fallback/预算预留前进入canonical_gateway_adapter，调用现有GatewayCompletionClient。规划固定保存的Qwen Agent；非规划沿原模型能力政策选择保存角色，语义修复等高能力门槛保留，轻量工作可用DeepSeek。不是因网络故障擅自跨Provider替代。

其他正式兼容_post_json调用同一预算客户端，且目标必须精确匹配保存Gateway的responses/chat路径。底层旧外部POST没有放开。预算只由GatewayCompletionClient预留一次；原预算、缓存、usage、调用阶段及未知提交锁存复用。规划/执行/修复调用按原purpose计数，原metrics在预算准入后才计入发送。缺run ledger、完整限制、价格估计，或额度不足，发送前拒绝。

文字messages/input及JSON Schema是当前桥的明确支持范围；stream、tool/image输入、未知字段/格式显式拒绝，不能悄悄剥离合同。raw文本由原上层合同继续准入，结构化请求继续验证schema。没有新增规划器、任务图、任务状态权威或公开交付出口。

通用5xx/损坏错误响应无法证明未提交时锁存UNKNOWN，不因Gateway换端口/令牌而允许重发同一请求。已明确before-send或已知拒绝才按失败处理。旧格式的遗留UNKNOWN缺乏安全迁移依据时要求人工核对，不清除记录。已完成缓存响应不重新发送。

本轮没有真实生成授权，也没有供应商模型POST。正式链路只用有界本地假Gateway验证：有预算完成一次请求处理，无预算/不足零POST，错误假输出仍被原任务合同阻断。真实生成和完整项目任务仍需单独授权；不能把此前三次/两元的未授权旧计划当作当前正式流程完成承诺，正式预检和修复也消耗调用预算。

## Gateway恢复

网络激活使用一个最多18秒的启动/锁等待窗口，不再有导入阶段45秒等待。MCP启动不等待网络激活，因此20秒宿主启动期限不会被Gateway启动耗时占用；HTTP/工具请求有各自截止时间，不把这称作操作系统硬实时保证。

session/status必须包含相同session_id、PID、OS创建时间和URL，且配置SHA/GUID匹配。发布以同目录临时文件关闭后os.replace完成，读取在短暂更新窗口有界重试。

- 原实例身份存活但健康检查失败：TEMPORARILY_UNREACHABLE_NO_RESTART，不另起实例。
- 配置/身份不匹配、无法读取OS身份或持有实例锁：明确拒绝；不靠PID猜测，不杀其他程序。
- OS确认原实例退出或PID已复用：持恢复锁重新核对，再确认原实例锁空闲，启动一个新实例并核验新会话。
- 同时发起恢复：有界等待后复用已恢复实例；不启动重复服务。

恢复只修复传输服务，从不清理预算/任务状态或重发请求。旧不可变client在会话变化时明确报domestic_gateway_changed；调用client.reconnect()得到新客户端，仅用于新的合法请求。原UNKNOWN请求仍由相同、与session/PID/端口无关的request identity阻止重放。

v1遗留会话没有可靠进程身份时不会冒险自动恢复。本机旧服务已正常停启迁移到v2；遇到其他旧目录时先正常停止已确认属于CGKN的服务，再由新入口启动。

## 停止、接口异常与回滚

维护前先停止当前生成调用/worker。原停止方式：

```powershell
cd D:\CGKN
python -X utf8 -m scripts.domestic_gateway stop
```

需要保持停服时，在应用配置关闭auto_start_gateway；不改全局网络。恢复为true后下一次网络调用会启动。接口身份、Up/物理属性或绑定变化仍使请求停止；修正已批准的成对应用/网络配置后正常重启Gateway，不能静默改为默认/VPN出口。

应用级回滚：退出旧插件进程，明确把config/domestic_application.json的mode改为legacy后重开；恢复国内则改回domestic。回滚将恢复旧客户端及其TUN依赖，不能用于绕过未核对UNKNOWN任务的约束。不要自动续跑这些任务。代码回滚按本轮baseline/changes.patch逐文件核对后来修改，不git reset/clean，不清任务、账本或Watchdog。

## 并发与证据边界

2026-10-29 的 503 收尾：`.cgkn/domestic-gateway/route-diagnostics.jsonl` 轮转保存每次认证 GET 的 request_id、Gateway 会话、配置摘要、上游状态及脱敏阶段。`last-route-probe.json` 保存最近检查；本地 503 的诊断正文现在会传回插件，不再只显示 HTTPError。`observed_progress=false` 表示本请求没有观察到该事件，连接复用时不等于没有建立过 TCP/TLS。日志不保存授权头、私有会话令牌或 API 响应正文。

插件摘要以 saved_roles 和 checked_providers 区分保存角色与本次清单检查，model=null、generation_executed=false；旧 gpt-4.1-mini 是 MCP 参数默认标签，并未触发该模型调用。Gateway ALIVE 与两家 Provider 结果分别显示，不能用 ALIVE 替代认证通过。

本次已用原安装命令启动新的 MCP 进程并复验。已加载旧代码的常驻 MCP 需要正常重开插件才能更新显示；磁盘源码更新不代表旧进程热加载。Gateway 按实例身份核对后通过原 stop 文件正常停止，再由原插件下一次网络请求自动恢复；不能按历史 PID/端口直接结束进程，也不自动重发未知提交。

生产POST没有诊断全局锁。Qwen/DeepSeek各有独立单线程网络执行池、一个Provider并发名额；名额等待最多1秒，诊断与生成共享对应Provider名额，不占另一家的机会。trace身份在网络执行线程显式设置，诊断用request_id映射收集自身事件，结束后删除，不收并发生成或另一Provider的记录。

物理出口完全无TUN、真实日常代理组切换仍NOT_VERIFIED；Pktmon自动审批拒绝被遵守。Docker默认bridge限制保留，生产Provider本轮实证为Windows。Grok可选禁用。两个既有目录方向门禁仍FAIL，本轮未删除它们或宣布整个项目PASS。
