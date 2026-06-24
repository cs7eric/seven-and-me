# Downloader

## 入口

- Route: `/downloader`
- Module: `frontend/src/views/downloader/index.tsx`
- Related design: `design/front/mp4-to-word.md`

## 数据源 / API

- 链接解析
  - `DOWNLOADER_API_BASE /parse`
- 向 MP4 to Word 交接
  - 前端不直接发处理请求
  - 通过 query 跳转到 `/mp4-to-word?mode=remote...`

## 页面职责

- 把视频/帖子链接解析成下载地址
- 展示 video/audio/link 结果
- 把解析结果转成 remote 模式参数，交给 MP4 to Word 页面继续处理

## 关键逻辑

- 当前页不持有转写任务，只负责“解析”和“移交”
- `Send to Parse` 本质是构造 query 参数并跳转，不是直接上传文件

## 代码入口

- `frontend/src/views/downloader/index.tsx`
- `frontend/src/views/downloader/components/*.tsx`
- `frontend/src/lib/api.ts`

## 维护要求

- 如果 Downloader 返回字段变化，记得同步更新本文档和 `mp4-to-word` 文档里的 remote 接管说明
