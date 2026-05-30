"use client"

import * as React from "react"
import {
  AudioWaveform,
  Download,
  FileText,
  GalleryVerticalEnd,
  LineChart,
} from "lucide-react"

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

const data = {
  user: {
    name: "cccs7",
    email: "csq020611@gmail.com",
    avatar: "/avatars/shadcn.jpg",
  },
  teams: [
    {
      name: "Application Hub",
      logo: GalleryVerticalEnd,
      plan: "Workspace",
    },
    {
      name: "Media Tools",
      logo: AudioWaveform,
      plan: "Pipeline",
    },
  ],
  navMain: [
    {
      title: "Downloader",
      url: "/downloader",
      icon: Download,
      items: [
        {
          title: "Open Downloader",
          url: "/downloader",
        },
      ],
    },
    {
      title: "MP4 to Word",
      url: "/mp4-to-word",
      icon: FileText,
      items: [
        {
          title: "Open Workspace",
          url: "/mp4-to-word",
        },
        {
          title: "History Records",
          url: "/mp4-to-word/history",
        },
      ],
    },
    {
      title: "Stock Review",
      url: "/stock-review",
      icon: LineChart,
      items: [
        {
          title: "Open Review",
          url: "/stock-review",
        },
      ],
    },
  ],
  projects: [
    {
      name: "Downloader",
      url: "/downloader",
      icon: Download,
    },
    {
      name: "MP4 to Word",
      url: "/mp4-to-word",
      icon: FileText,
    },
    {
      name: "MP4 History",
      url: "/mp4-to-word/history",
      icon: FileText,
    },
    {
      name: "Stock Review",
      url: "/stock-review",
      icon: LineChart,
    },
  ],
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher teams={data.teams} />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={data.navMain} />
        <NavProjects projects={data.projects} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={data.user} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
