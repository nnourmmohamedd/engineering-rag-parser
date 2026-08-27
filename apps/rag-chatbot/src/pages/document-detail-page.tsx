import { AlertTriangle, ArrowLeft, FileX2, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import Markdown from 'react-markdown';
import { Link, useNavigate, useParams } from 'react-router-dom';
import rehypeSanitize from 'rehype-sanitize';

import { EmptyState } from '@/components/layout/empty-state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { DocumentStatusBadge, JobStateBadge } from '@/components/ui/status-badge';
import {
  useDeleteDocument,
  useDocument,
  useDocumentPreview,
  useReprocessDocument,
  useRetryJob,
} from '@/hooks/use-documents';
import { useJobEvents } from '@/hooks/use-job-events';
import { formatBytes, formatDateTime, formatDuration, stageLabel } from '@/lib/utils';

export function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useDocument(documentId ?? null);
  const { data: preview } = useDocumentPreview(
    data?.document.status === 'READY' || data?.document.status === 'FAILED'
      ? (documentId ?? null)
      : null,
  );
  const reprocess = useReprocessDocument();
  const retry = useRetryJob();
  const deleteDocument = useDeleteDocument();
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const activeJob = data?.jobs.find((j) => j.state === 'QUEUED' || j.state === 'RUNNING');
  const { latest: liveEvent } = useJobEvents(activeJob?.job_id ?? null);

  if (!documentId) return null;

  if (isLoading) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="mx-auto max-w-4xl p-6">
        <EmptyState
          icon={FileX2}
          title="Document not found"
          description={
            error instanceof Error ? error.message : 'This document may have been deleted.'
          }
          action={
            <Button variant="outline" onClick={() => navigate('/documents')}>
              Back to documents
            </Button>
          }
        />
      </div>
    );
  }

  const { document, warnings, validation_summary, jobs } = data;
  const currentStage = liveEvent?.stage ?? activeJob?.stage;
  const currentProgress = liveEvent?.progress ?? activeJob?.progress ?? 0;

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <Link
        to="/documents"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to documents
      </Link>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="break-words text-xl font-semibold tracking-tight">
            {document.display_name}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <DocumentStatusBadge status={document.status} />
            {warnings.length > 0 && <Badge variant="warning">{warnings.length} warning(s)</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {(document.status === 'FAILED' || document.status === 'INTERRUPTED') &&
            activeJob === undefined && (
              <Button
                variant="outline"
                onClick={() => {
                  const failedJob = jobs.find((j) => j.retryable);
                  if (failedJob) retry.mutate(failedJob.job_id);
                }}
                disabled={retry.isPending}
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" /> Retry
              </Button>
            )}
          <Button
            variant="outline"
            onClick={() => reprocess.mutate({ documentId })}
            disabled={reprocess.isPending}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Reprocess
          </Button>
          <Button variant="destructive" onClick={() => setConfirmingDelete(true)}>
            <Trash2 className="h-4 w-4" aria-hidden="true" /> Delete
          </Button>
        </div>
      </div>

      {activeJob && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Processing</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
                {stageLabel(currentStage ?? 'QUEUED')}
              </span>
              <span className="text-muted-foreground">{Math.round(currentProgress * 100)}%</span>
            </div>
            <div
              role="progressbar"
              aria-valuenow={Math.round(currentProgress * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
            >
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-500"
                style={{ width: `${Math.round(currentProgress * 100)}%` }}
              />
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Metadata</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="Parser profile" value={document.parser_profile} />
            <Row label="File size" value={formatBytes(document.byte_size)} />
            <Row label="Pages" value={document.page_count?.toString() ?? '—'} />
            <Row label="Chunks indexed" value={document.total_chunks?.toString() ?? '—'} />
            <Row label="Uploaded" value={formatDateTime(document.created_at)} />
            <Row label="Last updated" value={formatDateTime(document.updated_at)} />
            <Row label="SHA-256" value={document.sha256} mono />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Index status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {Object.keys(validation_summary).length === 0 ? (
              <p className="text-muted-foreground">No validation summary recorded yet.</p>
            ) : (
              Object.entries(validation_summary).map(([key, value]) => (
                <Row key={key} label={key.replace(/_/g, ' ')} value={String(value)} />
              ))
            )}
          </CardContent>
        </Card>
      </div>

      {warnings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" /> Warnings
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-inside list-disc space-y-1 text-sm text-muted-foreground">
              {warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Processing history</CardTitle>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No jobs recorded.</p>
          ) : (
            <ul className="space-y-3">
              {jobs.map((job) => (
                <li key={job.job_id} className="rounded-md border p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">
                      Attempt {job.attempt} · {job.job_type}
                    </span>
                    <JobStateBadge state={job.state} />
                  </div>
                  {job.stage_timings.length > 0 && (
                    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-3">
                      {job.stage_timings.map((timing) => (
                        <div key={timing.stage} className="flex justify-between gap-2">
                          <dt>{stageLabel(timing.stage)}</dt>
                          <dd>{formatDuration(timing.duration_s)}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {job.error_message && (
                    <p className="mt-2 text-xs text-destructive">{job.error_message}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {preview && preview.markdown && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Extracted content preview</CardTitle>
          </CardHeader>
          <CardContent>
            {/* Document-derived Markdown is untrusted: raw HTML is sanitised, never rendered as-is. */}
            <div className="prose-engineering max-h-[32rem] overflow-y-auto rounded-md border bg-muted/30 p-4">
              <Markdown rehypePlugins={[rehypeSanitize]}>{preview.markdown}</Markdown>
            </div>
            {preview.truncated && (
              <p className="mt-2 text-xs text-muted-foreground">
                Preview truncated ({preview.total_characters.toLocaleString()} characters total).
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Dialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete "{document.display_name}"?</DialogTitle>
            <DialogDescription>
              This removes the document from the vector and keyword indexes, so it can no longer be
              searched or selected in new questions. Conversations that already cited it keep their
              citations, but those citations will be marked as unavailable. This cannot be undone
              from the interface.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmingDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                deleteDocument.mutate(documentId);
                setConfirmingDelete(false);
                navigate('/documents');
              }}
            >
              Delete document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="capitalize text-muted-foreground">{label}</dt>
      <dd
        className={mono ? 'truncate-middle max-w-[12rem] font-mono text-xs' : ''}
        title={mono ? value : undefined}
      >
        {value}
      </dd>
    </div>
  );
}
