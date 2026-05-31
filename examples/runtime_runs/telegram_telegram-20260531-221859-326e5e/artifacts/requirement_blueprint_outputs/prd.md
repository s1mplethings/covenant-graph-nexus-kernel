# Requirement Blueprint PRD

## Raw Requirement

以下是用户主导的模拟 Telegram 项目需求对话记录。 请只根据这份对话提取最终项目需求；不要自动套用 CRUD、任务看板、JSON 记录管理等默认模板；如果对话中要求真实项目/API测试，则保留该要求。运行时输入、输出和中间产物必须来自对话语义。 [observer/decision] API 已连接。 [customer/message] 你好 [service/message] 你好！请问有什么我可以帮助你的吗？ [customer/message] 我想要做一个帮我在游戏视频找高光片段的项目 [service/message] 我先按“游戏视频找高光片段”理解，输入是游戏视频文件，输出是多个 MP4 高光片段。高光的判断标准可以按默认的综合判断吗，还是你有指定的事件？ [customer/message] 输入时所有的视频都可以，然后输出就是mp4，高光就是一个一个视频的形式 [service/message] 我理解了，输入是所有类型的游戏视频文件，输出是多个 MP4 格式的高光片段，每个高光片段都是一个单独的视频。信息足够，可以生成项目。 [observer/criterion] 检测到对话里的生成意图，开始用当前对话生成项目并执行测试。

## Target Users

content_editor, streamer_operator, game_video_creator

## Core Features

- Video intake: Accept exactly one local game video file as the runtime input.
- Video metadata extraction: Read duration, mime type, file size, and preview metadata.
- Frame signal extraction: Sample visual/motion signal windows from the video timeline.
- Audio signal extraction: Detect audio peak and intensity windows that may indicate exciting moments.
- Language/subtitle signal extraction: Use speech, subtitle, or keyword signal when available without requiring manual event records.
- Highlight candidate generation: Fuse frame, audio, language, and short-window event density into candidate windows.
- Multi-criteria scoring: Rank candidates by motion, audio, language keywords, continuity, and user sensitivity settings.
- Clip export: Export separate MP4 highlight clips or a cut manifest that can be rendered losslessly from the source video.
- Settings UI: Let the user tune minimum clip duration and sensitivity without requiring technical setup.

## Technology Decisions

- file_input: custom CGNK rule (custom)
- local_video_preview: custom CGNK rule (custom)
- input_validation: custom CGNK rule (custom)
- video_metadata_probe: custom CGNK rule (custom)
- duration_detection: custom CGNK rule (custom)
- mime_type_validation: custom CGNK rule (custom)
- frame_sampling: custom CGNK rule (custom)
- motion_signal_detection: custom CGNK rule (custom)
- timeline_windowing: custom CGNK rule (custom)
- audio_peak_detection: custom CGNK rule (custom)
- energy_timeline: custom CGNK rule (custom)
- timeline_windowing: custom CGNK rule (custom)

## Acceptance

- The blueprint includes requirement, I/O, feature, capability, technology, architecture, API, database, frontend, task, and review artifacts.
- Level 3 gaps must be resolved before treating the blueprint as final.
- External technology freshness checks require explicit network approval.
