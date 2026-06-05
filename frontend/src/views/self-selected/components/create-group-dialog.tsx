import { useState } from "react"
import { Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import { GROUP_COLOR_OPTIONS, type GroupColorKey } from "../lib/constants"

interface CreateGroupDialogProps {
  onCreate: (payload: { name: string; color: GroupColorKey; description?: string }) => Promise<void>
}

export function CreateGroupDialog({ onCreate }: CreateGroupDialogProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [color, setColor] = useState<GroupColorKey>("blue")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setName("")
    setDescription("")
    setColor("blue")
    setError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError("分类名不能为空")
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await onCreate({ name: name.trim(), color, description: description.trim() || undefined })
      reset()
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "未知错误")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset()
        setOpen(next)
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="rounded-xl">
          <Plus className="size-3.5" />
          新建分类
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[440px]">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>新建自选分类</DialogTitle>
            <DialogDescription>
              分类会作为 tab 展示在页面顶部，后续可以往里面加股票。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="group-name">名称 *</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：长线持仓 / 短线观察"
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="group-description">描述</Label>
            <Input
              id="group-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="可选"
            />
          </div>

          <div className="space-y-2">
            <Label>颜色</Label>
            <div className="flex flex-wrap gap-2">
              {GROUP_COLOR_OPTIONS.map((opt) => {
                const active = color === opt.key
                return (
                  <button
                    key={opt.key}
                    type="button"
                    title={opt.label}
                    onClick={() => setColor(opt.key)}
                    className={`flex h-8 w-8 items-center justify-center rounded-full border transition-all ${
                      active
                        ? "ring-2 ring-offset-2 ring-foreground/30 scale-110 border-foreground/30"
                        : "border-border/30 hover:scale-105"
                    }`}
                  >
                    <span className={`size-4 rounded-full ${opt.dot}`} />
                  </button>
                )
              })}
            </div>
          </div>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              取消
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
