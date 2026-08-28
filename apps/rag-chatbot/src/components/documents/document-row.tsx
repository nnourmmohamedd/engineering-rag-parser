import { Loader2, MoreVertical, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { DocumentStatusBadge } from '@/components/ui/status-badge';
import { useDeleteDocument, useReprocessDocument, useRetryJob } from '@/hooks/use-documents';
import type { DocumentSummary } from '@/lib/types';
import { formatBytes, formatDateTime, truncateMiddle } from '@/lib/utils';

interface DocumentRowProps {
  document: DocumentSummary;
  latestJobId?: string;
}

export function DocumentRow({ document, latestJobId }: DocumentRowProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const reprocess = useReprocessDocument();
  const retry = useRetryJob();
  const deleteDocument = useDeleteDocument();

  const canRetry = document.status === 'FAILED' || document.status === 'INTERRUPTED';

  return (
    <>
      <tr className="border-b last:border-0 hover:bg-accent/40">
        <td className="max-w-[240px] px-3 py-3 sm:max-w-xs">
          <Link
            to={`/documents/${document.document_id}`}
            className="font-medium text-foreground underline-offset-4 hover:underline"
          >
            <span className="truncate-middle" title={document.display_name}>
              {truncateMiddle(document.display_name, 44)}
            </span>
          </Link>
          {document.warning_count > 0 && (
            <Badge variant="warning" className="mt-1">
              {document.warning_count} warning{document.warning_count === 1 ? '' : 's'}
            </Badge>
          )}
        </td>
        <td className="px-3 py-3">
          <DocumentStatusBadge status={document.status} />
        </td>
        <td className="hidden px-3 py-3 text-sm text-muted-foreground sm:table-cell">
          {document.total_chunks ?? '—'}
        </td>
        <td className="hidden px-3 py-3 text-sm text-muted-foreground md:table-cell">
          {document.page_count ?? '—'}
        </td>
        <td className="hidden px-3 py-3 text-sm text-muted-foreground md:table-cell">
          {formatBytes(document.byte_size)}
        </td>
        <td className="hidden px-3 py-3 text-sm text-muted-foreground lg:table-cell">
          {formatDateTime(document.created_at)}
        </td>
        <td className="px-3 py-3 text-right">
          <div className="flex items-center justify-end gap-1">
            {canRetry && latestJobId && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => retry.mutate(latestJobId)}
                disabled={retry.isPending}
                aria-label={`Retry processing ${document.display_name}`}
              >
                {retry.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                Retry
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Actions for ${document.display_name}`}
                >
                  <MoreVertical className="h-4 w-4" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem asChild>
                  <Link to={`/documents/${document.document_id}`}>View details</Link>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => reprocess.mutate({ documentId: document.document_id })}
                  disabled={reprocess.isPending}
                >
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Reprocess
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={() => setConfirmingDelete(true)}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </td>
      </tr>

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
                deleteDocument.mutate(document.document_id);
                setConfirmingDelete(false);
              }}
            >
              Delete document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
