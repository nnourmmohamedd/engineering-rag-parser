import { AlertOctagon } from 'lucide-react';
import { Component, type ErrorInfo, type ReactNode } from 'react';

import { Button } from '@/components/ui/button';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Last-resort UI boundary. A crash in one route must not blank the whole
 * application -- the user gets an explicit, real error and a way to recover.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Unhandled UI error', error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div
          className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center"
          role="alert"
        >
          <AlertOctagon className="h-10 w-10 text-destructive" aria-hidden="true" />
          <div className="space-y-1">
            <p className="text-sm font-semibold">Something went wrong in the interface.</p>
            <p className="max-w-md text-sm text-muted-foreground">{this.state.error.message}</p>
          </div>
          <Button onClick={this.reset}>Try again</Button>
        </div>
      );
    }
    return this.props.children;
  }
}
