/**
 * POC 页面 — Tabs 容器
 *
 * 如何新增 POC item:
 *   1. 在 poc/ 下新建目录，如 poc/my-idea/
 *   2. 该目录的 index.tsx 即为 POC 页面内容组件 (default export)
 *   3. 在 TABS_CONFIG 中加入一项即可出现在 Tab 列表
 */
import { Beaker } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { WorkspaceShell } from "@/layout/workspace-shell"

// ─── POC Item 配置 ───────────────────────────────────────────────────────────
// 格式: { key: string, label: string, component: React.ComponentType }
// key   — 唯一标识，同时作为 URL hash 和 Tabs value
// label — Tab 上显示的名称
// component — POC 内容组件 (lazy import 避免循环依赖)
// ─────────────────────────────────────────────────────────────────────────────
import DemoPoc from "./demo-poc"
import SentimentOverlayPoc from "./sentiment-overlay"

const TABS_CONFIG: { key: string; label: string; component: React.ComponentType }[] = [
  { key: "demo", label: "Demo", component: DemoPoc },
  { key: "sentiment-overlay", label: "情绪+上证叠加", component: SentimentOverlayPoc },
]

export default function PocPage() {
  return (
    <WorkspaceShell sectionLabel="POC" pageTitle="Proof of Concept">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <Beaker className="size-3.5" />
          POC
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Proof of Concept
          </h1>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-base">
            Proof of Concept 页面，用于快速验证新功能想法。
          </p>
        </div>
      </div>

      <Tabs defaultValue={TABS_CONFIG[0]?.key} className="w-full">
        <TabsList className="inline-flex h-fit w-fit max-w-full flex-wrap items-center gap-1 rounded-xl border border-border/30 bg-muted/35 p-1.5">
          {TABS_CONFIG.map((tab) => (
            <TabsTrigger
              key={tab.key}
              value={tab.key}
              className="inline-flex h-8 min-w-[100px] items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all data-[state=active]:bg-background data-[state=active]:shadow-sm"
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {TABS_CONFIG.map((tab) => {
          const Content = tab.component
          return (
            <TabsContent key={tab.key} value={tab.key} className="mt-4 space-y-4">
              <Content />
            </TabsContent>
          )
        })}
      </Tabs>
    </WorkspaceShell>
  )
}
