# MP4 to Word

## 入口

- Route: `/mp4-to-word`
- Module: `frontend/src/views/mp4-to-word/page.tsx`
- History route: `/mp4-to-word/history`
- History module: `frontend/src/views/mp4-to-word/history.tsx`
- Related backend design: `design/backend/mp4-history-reference-flow.md`

## 数据源 / API

- 本地上传 / 远程转入
  - `/api/transcribe`
  - `/api/parse-video`
- 处理态与 SSE
  - `/api/task/:taskId`
  - `/api/stream/:taskId`
- 结果导出 / 历史
  - `/api/reference/mp4-history`
  - `/api/reference/mp4-history/:id`
  - `/api/reference/mp4-history/:id/ask`

## 页面职责

- 承载本地上传与 Downloader 远程转入两种入口
- 通过 SSE 展示下载、上传、转写、polish、summary 进度
- 承接 summary 阅读、导出 markdown、保存 history、Ask AI
- history 页面负责列表和单条回放，不重新跑处理链路

## 关键逻辑

- 远程链路优先浏览器下载再上传，失败时回退服务端接管
- `taskId` 是主状态锚点，SSE 与 snapshot 都围绕它工作
- `history` 读的是 reference 落盘结果，不是实时任务态
- `Ask AI` 在实时页和 history 详情页都存在，但调用入口不同

## 代码入口

- `frontend/src/views/mp4-to-word/page.tsx`
- `frontend/src/views/mp4-to-word/history.tsx`
- `frontend/src/views/mp4-to-word/lib/*.ts`
- `frontend/src/lib/api.ts`

## 维护要求

- 如果改远程接管流程、SSE 事件结构、history 存储位置，先更新本文档和后端文档
