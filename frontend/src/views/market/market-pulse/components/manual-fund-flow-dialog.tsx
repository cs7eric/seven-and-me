/**
 * 手动粘贴资金流对话框.
 *
 * 流程:
 *   1. 用户点 "手动添加" 按钮 → 打开 dialog
 *   2. 选择目标交易日 (默认最近一个交易日, 可选历史任意一天)
 *   3. 粘贴 东方财富资金流 (https://data.eastmoney.com/zjlx/) 页面上的 5 行文本
 *   4. 解析器按行匹配, 实时显示解析结果
 *   5. 点 "保存" → POST 到后端, 落盘 reference/market-overview/fund-flow/manual/YYYYMMDD.json
 *   6. 前端 market-pulse 拉取并覆盖 overview 字段
 *
 * 解析容错: 容忍全角/半角冒号, 容忍不同空白分隔 (空格 / tab), 容忍单位后缀 "亿" / "%".
 */

import { useEffect, useMemo, useState } from "react"
import { Calendar as CalendarIcon, ExternalLink, Loader2, Save } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Calendar as CalendarUi } from "@/components/ui/calendar"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { notification } from "@/components/ui/notification"
import { toLocalDate, toLocalIso } from "@/lib/date-utils"
import { saveManualFundFlow, fetchManualFundFlow, type ManualFundFlow } from "@/lib/api"
import { getMostRecentTradingDayClient } from "../lib/trading-time"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Dialog 首次打开时的默认交易日 (一般为最近一个交易日). */
  initialTradingDate?: string
  /** 当前 manual 数据 (有值时显示 "已有 N 个字段" + 时间). */
  existing?: ManualFundFlow | null
  /** 保存成功后回调, 父组件重新拉取. */
  onSaved?: (saved: ManualFundFlow) => void
  /** 拉取所选日期的 existing 数据. 父组件按日期回传; 未提供时 dialog 走默认 fetchManualFundFlow. */
  onFetchExisting?: (tradingDate: string) => Promise<ManualFundFlow | null>
}

/** 5 行的 prefix → 字段映射. 顺序无关 (按行依次匹配). */
const ROW_MAP: Array<{ prefix: string; inflowKey: keyof ManualFundFlow; ratioKey: keyof ManualFundFlow }> = [
  { prefix: "主力",   inflowKey: "mainNetInflow",         ratioKey: "mainNetInflowRatio" },
  { prefix: "超大单", inflowKey: "superLargeNetInflow",   ratioKey: "superLargeNetInflowRatio" },
  { prefix: "大单",   inflowKey: "largeNetInflow",        ratioKey: "largeNetInflowRatio" },
  { prefix: "中单",   inflowKey: "mediumNetInflow",       ratioKey: "mediumNetInflowRatio" },
  { prefix: "小单",   inflowKey: "smallNetInflow",        ratioKey: "smallNetInflowRatio" },
]

const FIELD_LABELS: Record<string, string> = {
  mainNetInflow: "主力净流入",
  mainNetInflowRatio: "主力净比",
  superLargeNetInflow: "超大单净流入",
  superLargeNetInflowRatio: "超大单净比",
  largeNetInflow: "大单净流入",
  largeNetInflowRatio: "大单净比",
  mediumNetInflow: "中单净流入",
  mediumNetInflowRatio: "中单净比",
  smallNetInflow: "小单净流入",
  smallNetInflowRatio: "小单净比",
}

const INFLOW_UNIT = "亿"
const RATIO_UNIT = "%"

export function parseFundFlowText(text: string): { fields: ManualFundFlow; matchedLines: number } | { error: string } {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
  if (lines.length === 0) {
    return { error: "粘贴内容为空" }
  }
  const fields: Record<string, number> = {}
  let matchedLines = 0
  for (const line of lines) {
    // 取这一行的所有数字 (含负号和小数点)
    const numbers = line.match(/-?\d+(?:\.\d+)?/g)
    if (!numbers || numbers.length < 2) {
      continue
    }
    // 按 prefix 找第一个匹配的 ROW_MAP 项
    for (const row of ROW_MAP) {
      if (line.includes(row.prefix)) {
        fields[row.inflowKey as string] = parseFloat(numbers[0])
        fields[row.ratioKey as string] = parseFloat(numbers[1])
        matchedLines += 1
        break
      }
    }
  }
  if (matchedLines === 0) {
    return { error: "未识别到任何字段, 请确认是从东方财富资金流页面复制" }
  }
  return { fields: fields as unknown as ManualFundFlow, matchedLines }
}

export function ManualFundFlowDialog({
  open,
  onOpenChange,
  initialTradingDate,
  existing,
  onSaved,
  onFetchExisting,
}: Props) {
  const [text, setText] = useState("")
  const [saving, setSaving] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // dialog 自己维护目标日期, 默认走最近一个交易日. 父组件不再硬编码传 tradingDate.
  const fallbackInitial = initialTradingDate ?? getMostRecentTradingDayClient()
  const [tradingDate, setTradingDate] = useState<string>(fallbackInitial)
  // 选定日期对应的 existing 数据 (跟 selected tradingDate 联动, 跟 props.existing 解耦).
  const [dateExisting, setDateExisting] = useState<ManualFundFlow | null>(null)
  const [loadingExisting, setLoadingExisting] = useState(false)
  const [datePickerOpen, setDatePickerOpen] = useState(false)

  // 打开时: 重置为初始日期 + 清空粘贴框 + 重新拉取该日期的 existing.
  useEffect(() => {
    if (open) {
      setText("")
      setSubmitError(null)
      setTradingDate(fallbackInitial)
    }
    // 仅在 open 翻转时重置, 内部 tradingDate 变化不要重置
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // tradingDate 变化时, 拉对应日期的 existing (用父组件回调优先, 否则走默认 fetchManualFundFlow).
  useEffect(() => {
    let cancelled = false
    if (!open) return
    setLoadingExisting(true)
    const runner = onFetchExisting
      ? onFetchExisting(tradingDate)
      : (async () => {
          try {
            return await fetchManualFundFlow(tradingDate)
          } catch {
            return null
          }
        })()
    void runner
      .then((data) => {
        if (cancelled) return
        setDateExisting(data ?? null)
      })
      .finally(() => {
        if (!cancelled) setLoadingExisting(false)
      })
    return () => {
      cancelled = true
    }
  }, [tradingDate, open, onFetchExisting])

  const parseResult = useMemo(() => {
    if (!text.trim()) return null
    return parseFundFlowText(text)
  }, [text])

  const handleSave = async () => {
    if (!parseResult || "error" in parseResult) return
    setSaving(true)
    setSubmitError(null)
    try {
      const saved = await saveManualFundFlow({
        tradingDate,
        mainNetInflow: parseResult.fields.mainNetInflow,
        mainNetInflowRatio: parseResult.fields.mainNetInflowRatio,
        superLargeNetInflow: parseResult.fields.superLargeNetInflow,
        superLargeNetInflowRatio: parseResult.fields.superLargeNetInflowRatio,
        largeNetInflow: parseResult.fields.largeNetInflow,
        largeNetInflowRatio: parseResult.fields.largeNetInflowRatio,
        mediumNetInflow: parseResult.fields.mediumNetInflow,
        mediumNetInflowRatio: parseResult.fields.mediumNetInflowRatio,
        smallNetInflow: parseResult.fields.smallNetInflow,
        smallNetInflowRatio: parseResult.fields.smallNetInflowRatio,
      })
      notification.success({
        title: "已保存",
        description: `${tradingDate} 资金流手动数据已落盘 (${parseResult.matchedLines}/5 行)`,
      })
      setDateExisting(saved)
      onSaved?.(saved)
      onOpenChange(false)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setSubmitError(msg)
      notification.danger({ title: "保存失败", description: msg })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <DialogTitle className="flex flex-wrap items-center gap-2">
                <span>手动添加资金流</span>
                {/* 目标交易日选择器: 默认 = 最近一个交易日, 可改成历史任意一天.
                    走 Popover + react-day-picker, 不允许选未来日期. */}
                <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                      title="选择目标交易日 (默认最近一个交易日, 可选历史任意一天)"
                    >
                      <CalendarIcon className="size-3.5" />
                      <span className="font-mono tabular-nums">{tradingDate}</span>
                    </button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0" align="start">
                    <CalendarUi
                      mode="single"
                      selected={toLocalDate(tradingDate)}
                      onSelect={(d) => {
                        if (!d) return
                        setTradingDate(toLocalIso(d))
                        setDatePickerOpen(false)
                      }}
                      disabled={[
                        { after: new Date() },
                        (day) => {
                          const dow = day.getDay()
                          return dow === 0 || dow === 6
                        },
                      ]}
                      autoFocus
                    />
                  </PopoverContent>
                </Popover>
              </DialogTitle>
              <DialogDescription className="mt-1.5">
                从东方财富资金流页面复制 5 行文本 (主力 / 超大单 / 大单 / 中单 / 小单 各一行),
                粘贴到下方, 自动解析.
              </DialogDescription>
            </div>
            {/* 东方财富资金流外链: 从 header 搬过来, 用户点 "manual add" 后第一眼看到
                复制来源, 避免再开一个 tab 找页面. */}
            <a
              href="https://data.eastmoney.com/zjlx/"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-blue-700 dark:hover:bg-blue-950/40 dark:hover:text-blue-300"
            >
              <ExternalLink className="size-3.5" />
              <span>东方财富</span>
            </a>
          </div>
        </DialogHeader>

        <div className="space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              "今日主力净流入：    685.1762亿    主力净比：    2.26%\n" +
              "今日超大单净流入：  679.5597亿    超大单净比：  2.24%\n" +
              "今日大单净流入：      5.6166亿    大单净比：    0.02%\n" +
              "今日中单净流入：   -460.0474亿    中单净比：   -1.52%\n" +
              "今日小单净流入：   -225.1289亿    小单净比：   -0.74%"
            }
            rows={7}
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-800 focus:border-blue-400 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          />

          {/* 解析结果预览 */}
          {parseResult && "error" in parseResult ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
              {parseResult.error}
            </div>
          ) : parseResult ? (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-900/50">
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                解析结果 ({parseResult.matchedLines}/5 行)
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                {ROW_MAP.flatMap((row) => [
                  <div key={row.inflowKey} className="flex justify-between">
                    <span className="text-slate-500">{FIELD_LABELS[row.inflowKey]}</span>
                    <span className="font-mono tabular-nums text-slate-800 dark:text-slate-100">
                      {parseResult.fields[row.inflowKey]}{INFLOW_UNIT}
                    </span>
                  </div>,
                  <div key={row.ratioKey} className="flex justify-between">
                    <span className="text-slate-500">{FIELD_LABELS[row.ratioKey]}</span>
                    <span className="font-mono tabular-nums text-slate-800 dark:text-slate-100">
                      {parseResult.fields[row.ratioKey]}{RATIO_UNIT}
                    </span>
                  </div>,
                ])}
              </div>
            </div>
          ) : dateExisting ? (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
              {tradingDate} 已有 manual 数据{dateExisting.savedAt ? `, 保存于 ${dateExisting.savedAt}` : ""}. 重新粘贴会覆盖.
            </div>
          ) : loadingExisting ? (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900/50">
              正在加载 {tradingDate} 历史 manual 数据…
            </div>
          ) : null}

          {submitError ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {submitError}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            取消
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || !parseResult || "error" in parseResult}
          >
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
            <span className="ml-1">保存到 {tradingDate}</span>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
