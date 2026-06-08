import { createBrowserRouter } from "react-router-dom"
import App from "../App"
import ApplicationAnalysisPage from "../views/application-analysis"
import DashboardPage from "../views/dashboard"
import DownloaderPage from "../views/downloader"
import HomePage from "../views/home"
import HeatmapDemoPage, { HeatmapDataDebug } from "../views/heatmap-demo"
import IndustryApplicationPage from "../views/industry-application"
import Mp4ToWordPage from "../views/mp4-to-word"
import Mp4HistoryPage from "../views/mp4-to-word/history"
import SchedulerSettingsPage from "../views/settings/scheduler"
import SelfSelectedPage from "../views/self-selected"
import StockChartPage from "../views/stock-chart"
import StockOverviewPage from "../views/stock-overview"
import MarketPulseMock from "../views/stock-overview/mock-market"
import MarketPulsePage from "../views/market/market-pulse"
import MarketSentimentPage from "../views/market/market-sentiment"
import StockReviewPage from "../views/stock-review"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      {
        index: true,
        element: <HomePage />,
      },
      {
        path: "downloader",
        element: <DownloaderPage />,
      },
      {
        path: "dashboard",
        element: <DashboardPage />,
      },
      {
        path: "mp4-to-word",
        element: <Mp4ToWordPage />,
      },
      {
        path: "mp4-to-word/history",
        element: <Mp4HistoryPage />,
      },
      {
        path: "mp4-to-word/history/:id",
        element: <Mp4HistoryPage />,
      },
      {
        path: "stock-chart",
        element: <StockChartPage />,
      },
      {
        path: "stock-overview",
        element: <StockOverviewPage />,
      },
      {
        path: "stock-overview/market",
        element: <MarketPulseMock />,
      },
      {
        path: "market/pulse",
        element: <MarketPulsePage />,
      },
      {
        path: "market/sentiment",
        element: <MarketSentimentPage />,
      },
      {
        path: "stock-overview/application-analysis",
        element: <ApplicationAnalysisPage />,
      },
      {
        path: "stock-overview/industry-application",
        element: <IndustryApplicationPage />,
      },
      {
        path: "heatmap-demo",
        element: <HeatmapDemoPage />,
      },
      {
        path: "heatmap-data-debug",
        element: <HeatmapDataDebug />,
      },
      {
        path: "stock-overview/self-selected",
        element: <SelfSelectedPage />,
      },
      {
        path: "stock-review",
        element: <StockReviewPage />,
      },
      {
        path: "settings/scheduler",
        element: <SchedulerSettingsPage />,
      },
    ],
  },
])
