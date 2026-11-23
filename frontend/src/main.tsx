import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import ErrorBoundary from "./components/ErrorBoundary";
import "./index.css";

// One catch-all route: App keeps its own <Routes>, and useBlocker, which only
// a data router offers, can stop the app leaving a screen with unsaved edits.
const router = createBrowserRouter([
  {
    path: "*",
    element: (
      <AuthProvider>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </AuthProvider>
    ),
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
