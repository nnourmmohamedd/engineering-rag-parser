import type * as React from 'react';

import { cn } from '@/lib/utils';

interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 0-1, exactly as reported by the backend. Never interpolated or animated ahead. */
  value: number;
  label?: string;
}

/**
 * A determinate progress bar. The value shown is always a real backend-reported
 * position: the UI never invents motion to look busy.
 */
export function Progress({ value, label, className, ...props }: ProgressProps) {
  const percent = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? 'Progress'}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-secondary', className)}
      {...props}
    >
      <div
        className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
