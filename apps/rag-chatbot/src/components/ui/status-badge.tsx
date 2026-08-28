import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Loader2,
  OctagonX,
  PauseCircle,
  Trash2,
} from 'lucide-react';
import type { ComponentType } from 'react';

import { Badge, type BadgeProps } from './badge';
import type { DocumentStatus, JobState } from '@/lib/types';

/**
 * Status is communicated by icon + text, never by colour alone -- colour is
 * reinforcement for sighted users, not the signal itself.
 */
const DOCUMENT_STATUS: Record<
  DocumentStatus,
  { label: string; variant: BadgeProps['variant']; Icon: ComponentType<{ className?: string }> }
> = {
  UPLOADED: { label: 'Uploaded', variant: 'secondary', Icon: CircleDashed },
  PROCESSING: { label: 'Processing', variant: 'default', Icon: Loader2 },
  READY: { label: 'Ready', variant: 'success', Icon: CheckCircle2 },
  FAILED: { label: 'Failed', variant: 'destructive', Icon: OctagonX },
  INTERRUPTED: { label: 'Interrupted', variant: 'warning', Icon: PauseCircle },
  DELETING: { label: 'Deleting', variant: 'secondary', Icon: Trash2 },
  DELETED: { label: 'Deleted', variant: 'secondary', Icon: Trash2 },
};

const JOB_STATE: Record<
  JobState,
  { label: string; variant: BadgeProps['variant']; Icon: ComponentType<{ className?: string }> }
> = {
  QUEUED: { label: 'Queued', variant: 'secondary', Icon: CircleDashed },
  RUNNING: { label: 'Running', variant: 'default', Icon: Loader2 },
  READY: { label: 'Complete', variant: 'success', Icon: CheckCircle2 },
  FAILED: { label: 'Failed', variant: 'destructive', Icon: OctagonX },
  CANCELLED: { label: 'Cancelled', variant: 'warning', Icon: PauseCircle },
  INTERRUPTED: { label: 'Interrupted', variant: 'warning', Icon: AlertTriangle },
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const entry = DOCUMENT_STATUS[status];
  const { label, variant, Icon } = entry;
  return (
    <Badge variant={variant}>
      <Icon
        className={`h-3 w-3 ${status === 'PROCESSING' ? 'animate-spin' : ''}`}
        aria-hidden="true"
      />
      {label}
    </Badge>
  );
}

export function JobStateBadge({ state }: { state: JobState }) {
  const { label, variant, Icon } = JOB_STATE[state];
  return (
    <Badge variant={variant}>
      <Icon className={`h-3 w-3 ${state === 'RUNNING' ? 'animate-spin' : ''}`} aria-hidden="true" />
      {label}
    </Badge>
  );
}
