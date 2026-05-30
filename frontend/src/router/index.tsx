import { createBrowserRouter } from "react-router-dom"
import App from "../App"
import DownloaderPage from "../views/downloader"
import HomePage from "../views/home"
import Mp4ToWordPage from "../views/mp4-to-word"
import Mp4HistoryPage from "../views/mp4-to-word/history"
import StockChartPage from "../views/stock-chart"
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
        path: "stock-review",
        element: <StockReviewPage />,
      },
    ],
  },
])
