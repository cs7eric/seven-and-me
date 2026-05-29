import { createBrowserRouter } from "react-router-dom";
import App from "../App";
import HomePage from "../views/home";
import Mp4ToWordPage from "../views/mp4-to-word";

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
        path: "mp4-to-word",
        element: <Mp4ToWordPage />,
      },
    ],
  },
]);
