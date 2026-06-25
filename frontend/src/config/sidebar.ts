import {
  Activity,
  AudioWaveform,
  ComputerIcon,
  Download,
  FileText,
  Flame,
  GalleryVerticalEnd,
  LayoutDashboard,
  LineChart,
  Settings,
  BrainCircuit,
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
        {
          title: "downloader",
          url: "/downloader",
        },
      ],
    },
    {
      title: "market",
      url: "/market/pulse",
      icon: Activity,
      items: [
        {
          title: "market pulse",
          url: "/market/pulse",
        },
        {
          title: "market sentiment",
          url: "/market/sentiment",
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
          title: "chart",
          url: "/stock-chart",
        },
        {
          title: "market",
          url: "/stock-overview/market",
        },
        {
          title: "analysis",
          url: "/stock-overview/application-analysis",
        },
        {
          title: "industry",
          url: "/stock-overview/industry-application",
        },
        {
          title: "self-selected",
          url: "/stock-overview/self-selected",
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
        {
          title: "AI Provider",
          url: "/settings/ai-provider",
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
      name: "Market Pulse",
      url: "/stock-overview/market",
      icon: Flame,
    },
    {
      name: "Application Analysis",
      url: "/stock-overview/application-analysis",
      icon: LineChart,
    },
    {
      name: "Industry / Concept",
      url: "/stock-overview/industry-application",
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
      name: "Settings · AI Provider",
      url: "/settings/ai-provider",
      icon: BrainCircuit,
    },
    {
      name: "Knowledge Base",
      url: "/knowledge-base",
      icon: ComputerIcon,
    },
  ],
}
