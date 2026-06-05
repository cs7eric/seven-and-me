import {
  AudioWaveform,
  ComputerIcon,
  Download,
  FileText,
  GalleryVerticalEnd,
  LayoutDashboard,
  LineChart,
  Settings,
  TrendingUp,
} from "lucide-react"

export const sidebarConfig = {
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
      title: "Dashboard",
      url: "/dashboard",
      icon: LayoutDashboard,
    },
    {
      title: "Downloader",
      url: "/downloader",
      icon: Download,
    },
    {
      title: "MP4 to Word",
      url: "/mp4-to-word",
      icon: FileText,
      items: [
        {
          title: "open",
          url: "/mp4-to-word",
        },
        {
          title: "history",
          url: "/mp4-to-word/history",
        },
      ],
    },
    {
      title: "Stock Chart",
      url: "/stock-chart",
      icon: TrendingUp,
      items: [
        {
          title: "open",
          url: "/stock-chart",
        },
      ],
    },
    {
      title: "Stock Overview",
      url: "/stock-overview",
      icon: LineChart,
      items: [
        {
          title: "overview",
          url: "/stock-overview",
        },
        {
          title: "analysis",
          url: "/stock-overview/application-analysis",
        },
      ],
    },
    {
      title: "Stock Review",
      url: "/stock-review",
      icon: LineChart,
      items: [
        {
          title: "open",
          url: "/stock-review",
        },
      ],
    },
    {
      title: "Settings",
      url: "/settings/scheduler",
      icon: Settings,
      items: [
        {
          title: "Scheduler",
          url: "/settings/scheduler",
        },
      ],
    },
  ],
  projects: [
    {
      name: "Dashboard",
      url: "/dashboard",
      icon: LayoutDashboard,
    },
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
      name: "Stock Chart",
      url: "/stock-chart",
      icon: TrendingUp,
    },
    {
      name: "Stock Overview",
      url: "/stock-overview",
      icon: LineChart,
    },
    {
      name: "Application Analysis",
      url: "/stock-overview/application-analysis",
      icon: LineChart,
    },
    {
      name: "Stock Review",
      url: "/stock-review",
      icon: LineChart,
    },
    {
      name: "Settings · Scheduler",
      url: "/settings/scheduler",
      icon: Settings,
    },
    {
      name: "Knowledge Base",
      url: "/knowledge-base",
      icon: ComputerIcon,
    },
  ],
}
