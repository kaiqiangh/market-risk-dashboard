import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

/** Catches lazy-route chunk failures so a deploy does not leave a blank shell. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // Reload is the recovery path for a stale chunk after deployment.
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-8 text-center" role="alert">
        <h1 className="text-lg font-semibold text-foreground">Unable to load this page</h1>
        <p className="max-w-md text-sm text-muted-foreground">This page changed during a deployment. Reload to fetch the current version.</p>
        <Button variant="outline" onClick={() => window.location.reload()}>Reload</Button>
      </div>
    );
  }
}
