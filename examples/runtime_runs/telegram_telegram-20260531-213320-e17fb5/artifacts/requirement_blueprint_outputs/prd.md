# Requirement Blueprint PRD

## Raw Requirement

以下是用户主导的模拟 Telegram 项目需求对话记录。 请只根据这份对话提取最终项目需求；不要自动套用 CRUD、任务看板、JSON 记录管理等默认模板；如果对话中要求真实项目/API测试，则保留该要求。运行时输入、输出和中间产物必须来自对话语义。 [observer/decision] API 已连接。 [customer/message] 我想生成一个项目：输入任意游戏视频，自动找高光，分别导出 mp4 高光片段，用户可以设置最小时长和灵敏度。高光标准用综合判断：画面变化、动作强度、音频峰值、语音/字幕关键词、短时间内连续事件。信息够了，可以直接生成项目。 [service/message] 信息足够，可以生成项目。您的需求是构建一个项目，输入任意游戏视频，自动识别高光片段并导出为 mp4 格式，用户可以设置最小时长和灵敏度。高光的判断标准包括画面变化、动作强度、音频峰值、语音/字幕关键词和短时间内的连续事件。

## Target Users

developer_or_technical_lead

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
