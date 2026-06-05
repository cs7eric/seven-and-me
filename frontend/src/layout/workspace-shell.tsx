﻿﻿﻿﻿﻿import { Link } from "react-router-dom"
import type { ReactNode } from "react"
import { Home } from "lucide-react"

import { cn } from "@/lib/utils"
import { AppSidebar } from "@/layout/app-sidebar"
import { NotificationRoot } from "@/components/ui/notification"
import {
  GlobalCommandPalette,
  GlobalCommandTrigger,
} from "@/components/global-command-palette"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Separator } from "@/components/ui/separator"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"

interface WorkspaceShellProps {
  sectionLabel: string
  pageTitle: string
  /**
   * 默认 false，子 view 会被套 `p-6` 外 padding + `gap-6` 子元素间距。
   * 设为 true 时，去掉外层 p-6（保留 gap-6），用于 application-analysis 这种
   * 需要"全屏画布"、自己负责 padding 的页面。
   */
  fullBleed?: boolean
  children: ReactNode
}

export function WorkspaceShell({
  sectionLabel,
  pageTitle,
  fullBleed = false,
  children,
}: WorkspaceShellProps) {
  return (
    <SidebarProvider className="h-svh overflow-hidden">
      <AppSidebar className="border-sidebar-border/30" variant="inset" />
      <SidebarInset className="flex h-svh min-h-0 flex-col overflow-hidden md:!m-0 md:rounded-none md:border-0 md:border-l md:border-border/30 md:shadow-none">
        <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-2 border-b border-border/75 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="flex items-center gap-3 px-4">
            <SidebarTrigger />
            <Separator orientation="vertical" className="mr-1 h-4 bg-border/40" />
            <Breadcrumb>
              <BreadcrumbList>
                <BreadcrumbItem className="hidden md:flex">
                  <BreadcrumbLink
                    asChild
                    className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 hover:bg-muted/60"
                  >
                    <Link to="/">
                      <Home className="size-3.5" />
                      <span>Applications</span>
                    </Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator className="hidden md:block" />
                <BreadcrumbItem className="hidden md:flex">
                  <BreadcrumbLink
                    asChild
                    className="rounded-md px-1.5 py-1 text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                  >
                    <Link to="/">{sectionLabel}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator className="hidden md:block" />
                <BreadcrumbItem>
                  <BreadcrumbPage className="rounded-md bg-muted/40 px-2 py-1 font-medium">
                    {pageTitle}
                  </BreadcrumbPage>
                </BreadcrumbItem>
              </BreadcrumbList>
            </Breadcrumb>
          </div>
          <div className="ml-auto flex items-center gap-2 px-4">
            <GlobalCommandTrigger />
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div
            className={cn(
              "flex min-h-full flex-col gap-6",
              fullBleed ? "p-0" : "p-6"
            )}
          >
            {children}
          </div>
        </div>
      </SidebarInset>

      {/* 全局 notification 容器（portal 到 body） */}
      <NotificationRoot />

      {/* 全局 Alt+K 命令面板（portal 到 body） */}
      <GlobalCommandPalette />
    </SidebarProvider>
  )
}
