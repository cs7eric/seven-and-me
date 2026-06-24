/**
 * Design entry:
 * - Data/API: downloader parse endpoint + remote handoff to mp4-to-word
 * - Front design: design/front/downloader.md
 * - Related design: design/front/mp4-to-word.md
 * - Change rule: review design before edits; sync design if parse result fields or handoff flow changes.
 */
import { useState } from "react"
import { Loader2, Send, Video } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { WorkspaceShell } from "@/layout/workspace-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import type { DownloaderParseData, RemoteParsePayload } from "@/lib/api"
import { parseDownloaderUrl } from "@/lib/api"
import { LinkActionRow } from "./components/link-action-row"
import { LoadingState } from "./components/loading-state"
import { formatDuration } from "./lib/format"

export default function DownloaderPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState<DownloaderParseData | null>(null)
  const [copiedValue, setCopiedValue] = useState("")
  const [sendingToParse, setSendingToParse] = useState(false)
  const [sendToParseMessage, setSendToParseMessage] = useState("")

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedValue(value)
      window.setTimeout(() => {
        setCopiedValue((current) => (current === value ? "" : current))
      }, 1500)
    } catch {
      setError("复制失败，请手动复制链接")
    }
  }

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      setUrl(text)
      setError("")
    } catch {
      setError("无法读取剪贴板，请手动粘贴链接")
    }
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const trimmed = url.trim()
    if (!trimmed) {
      setError("请输入要解析的链接")
      return
    }

    setLoading(true)
    setError("")
    setResult(null)
    setSendToParseMessage("")

    try {
      const parsed = await parseDownloaderUrl(trimmed)
      setResult(parsed)
    } catch (err) {
      setError(err instanceof Error ? err.message : "解析失败")
    } finally {
      setLoading(false)
    }
  }

  const handleSendToParse = async () => {
    if (!result?.downloadVideoUrl || sendingToParse) return

    setSendingToParse(true)
    setSendToParseMessage("")
    setError("")

    try {
      const payload: RemoteParsePayload = {
        downloadUrl: result.downloadVideoUrl,
        title: result.title,
        sourceUrl: result.url,
        metadata: {
          title: result.title,
          platform: result.platform,
          duration: result.duration,
          noteType: result.noteType,
          download_audio_url: result.downloadAudioUrl,
          original_url: result.url,
        },
      }

      const params = new URLSearchParams({
        mode: "remote",
        downloadUrl: payload.downloadUrl,
        title: payload.title || "",
        sourceUrl: payload.sourceUrl || "",
        platform: String(payload.metadata?.platform || ""),
        duration: payload.metadata?.duration != null ? String(payload.metadata.duration) : "",
        noteType: String(payload.metadata?.noteType || ""),
        audioUrl: String(payload.metadata?.download_audio_url || ""),
      })

      setSendToParseMessage("正在跳转到 MP4 处理页面…")
      navigate(`/mp4-to-word?${params.toString()}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send to parse 失败")
      setSendingToParse(false)
    }
  }

  return (
    <WorkspaceShell sectionLabel="Downloader" pageTitle="Link Parser">
      <div className="mx-auto w-full max-w-[1400px]">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          <div className="hidden lg:block" />

          <div className="flex flex-col gap-4 lg:col-span-3">
            <Card className="shrink-0 border-border/30 shadow-none">
              <CardHeader className="space-y-1.5 p-4 pb-2">
                <h1 className="text-center text-2xl font-semibold tracking-tight">Downloader</h1>
                <p className="break-words text-center text-xs leading-relaxed text-foreground/60 sm:text-[13px]">
                  输入链接，直接拿到解析后的下载地址。
                </p>
              </CardHeader>
              <CardContent className="px-4 pb-4 pt-1">
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div className="space-y-2">
                    <textarea
                      value={url}
                      onChange={(event) => setUrl(event.target.value)}
                      placeholder="粘贴视频 / 帖子链接，例如 Bilibili、抖音、小红书等"
                      required
                      className="min-h-[120px] w-full resize-none rounded-md border border-border/30 bg-transparent px-3 py-2 text-sm outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40"
                    />
                    <div className="flex gap-2">
                      <Button type="button" variant="outline" className="flex-1 border-border/30" onClick={handlePaste}>
                        粘贴链接
                      </Button>
                      <Button type="submit" className="flex flex-1 items-center justify-center gap-2" disabled={loading || !url.trim()}>
                        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                        {loading ? "解析中..." : "解析链接"}
                      </Button>
                    </div>
                  </div>

                  {error ? <p className="text-center text-sm text-destructive">{error}</p> : null}
                </form>
              </CardContent>
            </Card>

            <Card className="border-border/30 shadow-none">
              <CardHeader className="p-3 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-base">Parse Result</CardTitle>
                  {result ? <Badge variant="secondary">{result.platform}</Badge> : null}
                </div>
                {result ? (
                  <p className="line-clamp-2 break-words text-[13px] leading-snug text-foreground/80">
                    {result.title}
                    {result.duration != null && (
                      <span className="ml-2 text-xs text-foreground/70">({formatDuration(result.duration)})</span>
                    )}
                  </p>
                ) : null}
              </CardHeader>
              <CardContent className="px-3 pb-3 pt-0">
                {loading ? (
                  <LoadingState />
                ) : !result ? (
                  <div className="rounded-lg bg-muted/20 px-4 py-12 text-center text-sm text-muted-foreground">
                    解析结果会显示在这里。
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="border-border/30">{result.platform}</Badge>
                        <Badge variant="secondary">{result.noteType || "video"}</Badge>
                        {result.duration ? <Badge variant="outline" className="border-border/30">{formatDuration(result.duration)}</Badge> : null}
                      </div>
                      <p className="text-sm leading-6 text-muted-foreground">
                        {result.desc || "暂无描述"}
                      </p>
                      <div className="grid gap-2">
                        <LinkActionRow
                          label="Video Download"
                          value={result.downloadVideoUrl}
                          copied={copiedValue === result.downloadVideoUrl}
                          onCopy={handleCopy}
                        />
                        <LinkActionRow
                          label="Audio Download"
                          value={result.downloadAudioUrl}
                          copied={copiedValue === result.downloadAudioUrl}
                          onCopy={handleCopy}
                        />
                      </div>
                    </div>

                    <Separator className="bg-border/40" />

                    <div className="rounded-md bg-muted/20 p-4">
                      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
                        <Send className="size-4" />
                        send to parse
                      </div>
                      <p className="mb-3 text-sm leading-6 text-muted-foreground">
                        下载已解析完成的视频文件，并将其作为输入源传递给 MP4 to Word 模块，启动转写、AI polish 与 summary 工作流。
                      </p>
                      <div className="flex flex-wrap items-center gap-3">
                        <Button onClick={handleSendToParse} disabled={!result.downloadVideoUrl || sendingToParse}>
                          {sendingToParse ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                          {sendingToParse ? "Sending..." : "Send to Parse"}
                        </Button>
                        {sendToParseMessage ? (
                          <span className="text-sm text-muted-foreground">{sendToParseMessage}</span>
                        ) : null}
                      </div>
                    </div>

                    {result.pages?.length ? (
                      <>
                        <Separator className="bg-border/40" />
                        <div className="space-y-2">
                          <div className="text-sm font-medium text-foreground">Multi-part Items</div>
                          <div className="space-y-2">
                            {result.pages.map((page) => (
                              <div key={`${page.cid}-${page.page}`} className="rounded-md bg-muted/20 p-3">
                                <div className="mb-2 flex items-center justify-between gap-4 text-sm">
                                  <span className="font-medium text-foreground">P{page.page} · {page.part}</span>
                                  <span className="text-xs text-muted-foreground">{formatDuration(page.duration)}</span>
                                </div>
                                <div className="grid gap-2">
                                  <LinkActionRow
                                    label="Video"
                                    value={page.downloadVideoUrl}
                                    copied={copiedValue === page.downloadVideoUrl}
                                    onCopy={handleCopy}
                                  />
                                  <LinkActionRow
                                    label="Audio"
                                    value={page.downloadAudioUrl}
                                    copied={copiedValue === page.downloadAudioUrl}
                                    onCopy={handleCopy}
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </>
                    ) : null}

                    {result.videos?.length ? (
                      <>
                        <Separator className="bg-border/40" />
                        <div className="space-y-2">
                          <div className="text-sm font-medium text-foreground">Embedded Videos</div>
                          <div className="space-y-2">
                            {result.videos.map((video) => (
                              <div key={video.id} className="rounded-md bg-muted/20 p-3">
                                <div className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
                                  <Video className="size-4" />
                                  {video.title}
                                </div>
                                <div className="grid gap-2">
                                  <LinkActionRow
                                    label="Video"
                                    value={video.downloadVideoUrl}
                                    copied={copiedValue === video.downloadVideoUrl}
                                    onCopy={handleCopy}
                                  />
                                  <LinkActionRow
                                    label="Audio"
                                    value={video.downloadAudioUrl}
                                    copied={copiedValue === video.downloadAudioUrl}
                                    onCopy={handleCopy}
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </>
                    ) : null}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="hidden lg:block" />
        </div>
      </div>
    </WorkspaceShell>
  )
}