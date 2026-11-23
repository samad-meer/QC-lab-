import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

/** A screen that breaks says so and offers a way back, rather than leaving a blank page. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
        <div className="msg error" role="alert">
          <span className="msg-icon">!</span>
          <span>
            This screen ran into a problem. Nothing you saved has been lost.{" "}
            <button className="ghost small" onClick={() => window.location.assign("/")}>Go to the start</button>
          </span>
        </div>
      </main>
    );
  }
}
