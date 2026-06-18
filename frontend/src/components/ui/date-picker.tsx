import * as React from "react"
import { CalendarIcon, XIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { toLocalDate, toLocalIso, todayLocal } from "@/lib/date-utils"

interface DatePickerProps {
  /** 选中日期 (ISO 字符串 YYYY-MM-DD 或 Date). undefined = 未选. */
  value: string | Date | null | undefined
  /** 选中回调, 传 Date 给上层 (本地 00:00). 清空时传 null. */
  onChange: (date: Date | null) => void
  /** 最大可选日期 (默认今天, 本地时区). 用于限制不能选未来日. */
  maxDate?: Date
  /** 占位文本. */
  placeholder?: string
  /** 触发器右侧展示的辅助文本. */
  trailing?: React.ReactNode
  /** 触发器 button className. */
  triggerClassName?: string
  /** 是否显示清空按钮 (有值时). */
  clearable?: boolean
  id?: string
  "aria-label"?: string
}

/** 单一日期选择器 (Popover + Calendar).
 *
 * - 走 shadcn Calendar (react-day-picker v10) + 内部 Popover.
 * - value 用 string (YYYY-MM-DD) 或 Date 都接受.
 * - onChange 回调统一传 Date (本地 00:00) 给上层, 上层用 toLocalIso(d) 序列化.
 * - 单日选择模式 (mode="single" 是 Calendar 的默认).
 * - maxDate 默认今天 (不能选未来, 含周末).
 * - 时区: 全程本地时区方法, 不用 UTC, 避免 "选 6/18 落到 6/17" 之类错位.
 */
export function DatePicker({
  value,
  onChange,
  maxDate,
  placeholder = "选择日期",
  trailing,
  triggerClassName,
  clearable = true,
  id,
  "aria-label": ariaLabel,
}: DatePickerProps) {
  const selected = toLocalDate(value)
  const displayText = selected ? toLocalIso(selected) : placeholder
  const max = maxDate ?? todayLocal()

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant="outline"
          size="sm"
          aria-label={ariaLabel ?? placeholder}
          className={cn(
            "h-8 justify-start gap-1.5 rounded-md bg-background px-2.5 text-xs font-normal tabular-nums",
            !selected && "text-muted-foreground",
            triggerClassName
          )}
        >
          <CalendarIcon className="size-3.5" />
          <span>{displayText}</span>
          {trailing}
          {clearable && selected && (
            <span
              role="button"
              tabIndex={-1}
              aria-label="清空日期"
              className="-mr-1 ml-1 flex size-4 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                onChange(null)
              }}
              onPointerDown={(e) => {
                // 阻止 Popover 误关
                e.stopPropagation()
              }}
            >
              <XIcon className="size-3" />
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={selected}
          onSelect={(d) => onChange(d ?? null)}
          // 禁用: 未来日 + 周末 (A 股周末无数据). 周末用本地 weekday 判断.
          disabled={[
            { after: max },
            (date) => {
              const dow = date.getDay()
              return dow === 0 || dow === 6
            },
          ]}
          autoFocus
        />
      </PopoverContent>
    </Popover>
  )
}
