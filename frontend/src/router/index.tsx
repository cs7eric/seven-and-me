import { createBrowserRouter } from "react-router-dom"
import App from "../App"
import DownloaderPage from "../views/downloader"
import HomePage from "../views/home"
import Mp4ToWordPage from "../views/mp4-to-word"
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
        path: "stock-review",
        element: <StockReviewPage />,
      },
    ],
  },
])
