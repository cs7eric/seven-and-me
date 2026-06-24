# Transcription Runtime Flow

## Required Entry

后续任何人如果要改 MP4 转写、远程解析接管、SSE 推送或任务运行态，请先看本文。

相关文件：

- `F:\dev-repo\mp4-to-word-new\design\backend\transcription-runtime-flow.md`
- `F:\dev-repo\mp4-to-word-new\backend\api\transcription.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\transcription_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\export_service.py`
- `F:\dev-repo\mp4-to-word-new\backend\api\mp4_history.py`
- `F:\dev-repo\mp4-to-word-new\backend\services\mp4_history_service.py`

要求：

- 先更新本文档，再改代码
- 改完代码后，必须把本文档同步回写

## Scope

这条链路覆盖：

- 本地上传 -> 转写
- Downloader 远程资源 -> 服务端接管下载 -> 转写
- 任务态查询
- SSE 事件流
- 导出 markdown

## Runtime Model

### 1. `task_id` 是唯一主键

- 前端实时页所有状态都围绕 `task_id`
- `/api/task/<task_id>` 提供 snapshot
- `/api/stream/<task_id>` 提供流式事件

### 2. 状态机

主状态大致为：

- `downloading`
- `transcribing`
- `polishing`
- `summarizing`
- `done`
- `error`

其中 `download_progress` 与 `intake_progress` 是附加进度块，不是独立任务。

## Main Flows

### 1. 本地上传

- route: `POST /api/transcribe`
- flow:
  - 保存上传文件到 `UPLOAD_FOLDER`
  - `runtime_store.create_task_record`
  - `start_transcription_task(...)`

### 2. 远程解析接管

- route: `POST /api/parse-video`
- flow:
  - 校验 `download_url`
  - `queue_remote_parse(...)`
  - 后台线程先下载，再调用 `start_transcription_task(...)`

### 3. 转写执行

- `start_transcription_task(...)`
- video 先转 WAV；audio 直接进 transcriber
- 回调不断更新 `runtime_store` 里的 transcript / polished / summary

### 4. SSE

- route: `GET /api/stream/<task_id>`
- 由轮询 `runtime_store` 状态生成事件
- 事件包括：
  - `download_start`
  - `download_progress`
  - `ingest_progress`
  - `transcribe_start`
  - `chunk`
  - `polish_start`
  - `polish_char`
  - `summary_start`
  - `summary_char`
  - `done`
  - `error`

## Boundary Rules

- API 层只负责暴露任务入口、snapshot、SSE 和导出
- 真正的下载、音视频转换、transcribe、polish、summary 在 service 层
- history 落盘不属于实时链路本身，属于后续导出链路，见 `mp4-history-reference-flow.md`

## Maintenance Notes

- 改状态机或 SSE event 名称时，必须同步更新前端 `mp4-to-word` 页面
- 改 runtime_store 字段名时，要同时检查：
  - `/api/task/<task_id>`
  - `/api/stream/<task_id>`
  - history 导出 snapshot
