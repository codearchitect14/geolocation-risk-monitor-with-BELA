"use client";

import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    console.error("Application error:", error.message);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-lg p-10 text-center">
        <h1 className="text-h3 text-ink">This page hit an error</h1>
        <p className="mt-2 text-small text-slate-600">
          Your data is safe. Reload the page, or go back to the overview.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Button onClick={() => this.setState({ error: null })}>Try again</Button>
          <Button variant="secondary" onClick={() => (window.location.href = "/app")}>
            Overview
          </Button>
        </div>
      </div>
    );
  }
}
