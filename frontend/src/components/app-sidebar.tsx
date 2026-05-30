"use client"

import * as React from "react"

import { sidebarConfig } from "@/config/sidebar"
import { NavMain } from "@/components/nav-main"
import { NavProjects } from "@/components/nav-projects"
import { NavUser } from "@/components/nav-user"
import { TeamSwitcher } from "@/components/team-switcher"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
} from "@/components/ui/sidebar"

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher teams={sidebarConfig.teams} />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={sidebarConfig.navMain} />
        <NavProjects projects={sidebarConfig.projects} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={sidebarConfig.user} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
