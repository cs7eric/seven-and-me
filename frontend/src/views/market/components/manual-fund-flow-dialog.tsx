/**
 * 手动粘贴资金流对话框.
 *
 * 流程:
 *   1. 用户点 "手动添加" 按钮 → 打开 dialog
 *   2. 粘贴 东方财富资金流 (https://data.eastmoney.com/zjlx/) 页面上的 5 行文本
 *   3. 解析器按行匹配, 实时显示解析结果
 *   4. 点 "保存" → POST 到后端, 落盘 reference/market-overview/fund-flow/manual/YYYYMMDD.json
 *   5. 前端 market-pulse 拉取并覆盖 overview 字段
 *
 * 解析容错: 容忍全角/半角冒号, 容忍不同空白分隔 (空格 / tab), 容忍单位后缀 "亿" / "%".
 */

import { useEffect, useMemo, useState } from "react"
import { Loader2, Save } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { notification } from "@/components/ui/notification"
import { saveManualFundFlow, type ManualFundFlow } from "@/lib/api"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  tradingDate: string
  /** 当前 manual 数据 (有值时显示 "已有 N 个字段" + 时间). */
  existing?: ManualFundFlow | null
  /** 保存成功后回调, 父组件重新拉取. */
  onSaved?: (saved: ManualFundFlow) => void
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

export function ManualFundFlowDialog({ open, onOpenChange, tradingDate, existing, onSaved }: Props) {
  const [text, setText] = useState("")
  const [saving, setSaving] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 打开时清空, 关闭时不清 (避免下次打开又空)
  useEffect(() => {
    if (open) {
      setText("")
      setSubmitError(null)
    }
  }, [open])

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
          <DialogTitle>手动添加 {tradingDate} 资金流</DialogTitle>
          <DialogDescription>
            从{" "}
            <a
              href="https://data.eastmoney.com/zjlx/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 underline-offset-2 hover:underline dark:text-blue-400"
            >
              东方财富资金流
            </a>{" "}
            页面复制 5 行文本 (主力 / 超大单 / 大单 / 中单 / 小单 各一行), 粘贴到下方, 自动解析.
          </DialogDescription>
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
          ) : existing ? (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
              已有 manual 数据, 保存于 {existing.savedAt}. 重新粘贴会覆盖.
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
            <span className="ml-1">保存</span>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
