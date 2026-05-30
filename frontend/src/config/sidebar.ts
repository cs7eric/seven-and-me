import {
  AudioWaveform,
  Download,
  FileText,
  GalleryVerticalEnd,
  LineChart,
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
      name: "Stock Chart",
      url: "/stock-chart",
      icon: TrendingUp,
    },
    {
      name: "Stock Review",
      url: "/stock-review",
      icon: LineChart,
    },
  ],
}
