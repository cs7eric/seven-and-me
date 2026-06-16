import { useInView, useMotionValue, useSpring } from "motion/react"
import { useCallback, useEffect, useRef } from "react"

/**
 * 数字滚动动画 (CountUp · react-bits @react-bits/CountUp-TS-TW)
 *
 * 用途: 大盘成交额 / 上涨 / 下跌 / 涨停 / 跌停 / 主力净流入 等数字
 *       每次 overview 轮询更新时做一次 ease 动画.
 *
 * 关键行为:
 *   - 默认 useInView({ once: true }) → 数字首次进入视口时播放一次.
 *     但需求是 "每次更新都动", 因此调用方应传 `key={value}`,
 *     父级 re-render 时 React 卸载旧实例并挂载新实例 → 重新触发 inView 动画.
 *   - 父级 className / 字体颜色 / 样式不变, 通过 className prop 透传.
 *   - to/from 必须是 number (本组件内部 Intl.NumberFormat 格式化);
 *     "亿" / "+" / "—" 之类的前后缀请用 prefix/suffix 渲染在外部.
 */
interface CountUpProps {
  to: number
  from?: number
  direction?: "up" | "down"
  delay?: number
  duration?: number
  className?: string
  startWhen?: boolean
  separator?: string
  onStart?: () => void
  onEnd?: () => void
}

export function CountUp({
  to,
  from = 0,
  direction = "up",
  delay = 0,
  duration = 2,
  className = "",
  startWhen = true,
  separator = "",
  onStart,
  onEnd,
}: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const motionValue = useMotionValue(direction === "down" ? to : from)

  const damping = 20 + 40 * (1 / duration)
  const stiffness = 100 * (1 / duration)

  const springValue = useSpring(motionValue, { damping, stiffness })

  const isInView = useInView(ref, { once: true, margin: "0px" })

  const getDecimalPlaces = (num: number): number => {
    const str = num.toString()
    if (str.includes(".")) {
      const decimals = str.split(".")[1]
      if (parseInt(decimals) !== 0) {
        return decimals.length
      }
    }
    return 0
  }

  const maxDecimals = Math.max(getDecimalPlaces(from), getDecimalPlaces(to))

  const formatValue = useCallback(
    (latest: number) => {
      const hasDecimals = maxDecimals > 0
      const options: Intl.NumberFormatOptions = {
        useGrouping: !!separator,
        minimumFractionDigits: hasDecimals ? maxDecimals : 0,
        maximumFractionDigits: hasDecimals ? maxDecimals : 0,
      }
      const formattedNumber = Intl.NumberFormat("en-US", options).format(latest)
      return separator ? formattedNumber.replace(/,/g, separator) : formattedNumber
    },
    [maxDecimals, separator],
  )

  useEffect(() => {
    if (ref.current) {
      ref.current.textContent = formatValue(direction === "down" ? to : from)
    }
  }, [from, to, direction, formatValue])

  useEffect(() => {
    if (isInView && startWhen) {
      if (typeof onStart === "function") onStart()
      const timeoutId = setTimeout(() => {
        motionValue.set(direction === "down" ? from : to)
      }, delay * 1000)
      const durationTimeoutId = setTimeout(() => {
        if (typeof onEnd === "function") onEnd()
      }, delay * 1000 + duration * 1000)
      return () => {
        clearTimeout(timeoutId)
        clearTimeout(durationTimeoutId)
      }
    }
  }, [isInView, startWhen, motionValue, direction, from, to, delay, onStart, onEnd, duration])

  useEffect(() => {
    const unsubscribe = springValue.on("change", (latest: number) => {
      if (ref.current) ref.current.textContent = formatValue(latest)
    })
    return () => unsubscribe()
  }, [springValue, formatValue])

  return <span className={className} ref={ref} />
}
