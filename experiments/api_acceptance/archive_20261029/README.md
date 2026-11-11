# 已归档的 ITER-117/118 付费验收入口

这些实现仅供历史审计和本地假 Provider 回归；正式 MCP 不再暴露付费启动入口。默认工作区历史计划显式拒绝执行 ARCHIVED_ACCEPTANCE_LIVE_DISABLED。测试使用临时目录和阻断外网的假 Provider。不要移除该防护或把旧授权复制成新授权。

原 artifacts、.cgkn/streaming-acceptance-jobs、预算和UNKNOWN均未迁移或删除。历史状态可通过正式只读 cgkn_streaming_acceptance_status 查询。正常生产路径仍为 cgkn_generate → 原generation_command/controller → budgeted Gateway；本目录没有新的业务权威。
