import { Link } from "react-router-dom"
import type { ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
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
  children: ReactNode
}

export function WorkspaceShell({
  sectionLabel,
  pageTitle,
  children,
}: WorkspaceShellProps) {
  return (
    <SidebarProvider>
      <AppSidebar className="border-sidebar-border/30" variant="inset" />
      <SidebarInset className="md:m-0 md:rounded-none md:border-0 md:border-l md:border-border/30 md:shadow-none">
        <header className="flex h-16 shrink-0 items-center gap-2 border-b border-border/20 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="flex items-center gap-3 px-4">
            <SidebarTrigger />
            <Separator orientation="vertical" className="mr-1 h-4 bg-border/40" />
            <Breadcrumb>
              <BreadcrumbList>
                <BreadcrumbItem className="hidden md:block">
                  <BreadcrumbLink asChild>
                    <Link to="/">Applications</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator className="hidden md:block" />
                <BreadcrumbItem className="hidden md:block">
                  <BreadcrumbPage>{sectionLabel}</BreadcrumbPage>
                </BreadcrumbItem>
                <BreadcrumbSeparator className="hidden md:block" />
                <BreadcrumbItem>
                  <BreadcrumbPage>{pageTitle}</BreadcrumbPage>
                </BreadcrumbItem>
              </BreadcrumbList>
            </Breadcrumb>
          </div>
        </header>

        <div className="flex flex-1 flex-col gap-6 p-6">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  )
}
