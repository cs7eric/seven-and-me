export interface DashboardCard {
  title: string
  description: string
}

export const dashboardCards: DashboardCard[] = [
  {
    title: "MP4 转写（今日）",
    description: "今日上传 / 转写 / 导出次数、累计时长、平均 polish 时长。后续接 `application-analysis-store` + `task_runtime_service` 统计。",
  },
  {
    title: "市场概览（A股）",
    description: "今日 A 股上涨家数、领涨 / 领跌行业、成交量、北向资金。后续接 `market_overview_service` / `market_overview_metrics`。",
  },
  {
    title: "调度任务",
    description: "当前在跑的 scheduler 数量、最近一次执行的成功 / 失败比、下一次预计触发时间。后续接 `/api/scheduler/jobs`。",
  },
  {
    title: "近 7 天活动",
    description: "转写 / 提问 / 导出 / 修改 workspace 的时间线摘要。后续从 `task_runtime_service` + `mp4-history` 聚合。",
  },
  {
    title: "未读 Ask AI",
    description: "MP4 Ask AI 还没回复的 question 数量。后续接 `/api/ask` 聚合。",
  },
  {
    title: "存储 / 模型状态",
    description: "Whisper 模型是否已加载、`reference/` 占用空间、待清理历史。后续接 `/api/system/model-info` + 文件统计。",
  },
]
