/**
 * Demo POC — 占位示例
 *
 * 如何新增 POC item:
 *   1. 在 poc/ 下新建目录，如 poc/my-idea/
 *   2. 该目录的 index.tsx 即为 POC 页面内容组件
 *   3. 在 poc/index.tsx 的 TABS_CONFIG 中加入一项即可出现在 Tab 列表
 */
export default function DemoPoc() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          这是 Demo POC 占位页面。
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          在 <code className="rounded bg-muted px-1">poc/demo-poc/</code> 下创建你的 POC 内容，
          然后在 <code className="rounded bg-muted px-1">poc/index.tsx</code> 的 TABS_CONFIG 中注册即可。
        </p>
      </div>
    </div>
  )
}
