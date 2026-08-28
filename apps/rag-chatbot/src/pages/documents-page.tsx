import { FileSearch, FileX2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { DocumentRow } from '@/components/documents/document-row';
import { UploadDropzone } from '@/components/documents/upload-dropzone';
import { EmptyState } from '@/components/layout/empty-state';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useDocuments } from '@/hooks/use-documents';
import type { DocumentStatus } from '@/lib/types';

const STATUS_FILTERS: { value: DocumentStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All statuses' },
  { value: 'READY', label: 'Ready' },
  { value: 'PROCESSING', label: 'Processing' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'INTERRUPTED', label: 'Interrupted' },
  { value: 'UPLOADED', label: 'Uploaded' },
];

type SortKey = 'newest' | 'oldest' | 'name';

export function DocumentsPage() {
  const { data: documents, isLoading, isError, error } = useDocuments();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | 'all'>('all');
  const [sortKey, setSortKey] = useState<SortKey>('newest');

  const filtered = useMemo(() => {
    let rows = documents ?? [];
    if (statusFilter !== 'all') rows = rows.filter((d) => d.status === statusFilter);
    if (search.trim()) {
      const needle = search.trim().toLowerCase();
      rows = rows.filter((d) => d.display_name.toLowerCase().includes(needle));
    }
    const sorted = [...rows];
    if (sortKey === 'newest') sorted.sort((a, b) => b.created_at.localeCompare(a.created_at));
    if (sortKey === 'oldest') sorted.sort((a, b) => a.created_at.localeCompare(b.created_at));
    if (sortKey === 'name') sorted.sort((a, b) => a.display_name.localeCompare(b.display_name));
    return sorted;
  }, [documents, search, statusFilter, sortKey]);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Documents</h1>
        <p className="text-sm text-muted-foreground">
          Upload engineering PDFs for parsing, chunking and indexing. Only documents marked{' '}
          <span className="font-medium text-foreground">Ready</span> can be selected for questions.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Upload</CardTitle>
        </CardHeader>
        <CardContent>
          <UploadDropzone />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:space-y-0">
          <CardTitle className="text-base">All documents</CardTitle>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              placeholder="Search by name…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-label="Search documents by name"
              className="sm:w-48"
            />
            <Select
              value={statusFilter}
              onValueChange={(value) => setStatusFilter(value as typeof statusFilter)}
            >
              <SelectTrigger aria-label="Filter by status" className="sm:w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_FILTERS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={sortKey} onValueChange={(value) => setSortKey(value as SortKey)}>
              <SelectTrigger aria-label="Sort documents" className="sm:w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="newest">Newest first</SelectItem>
                <SelectItem value="oldest">Oldest first</SelectItem>
                <SelectItem value="name">Name (A-Z)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="space-y-2" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          )}

          {isError && (
            <EmptyState
              icon={FileX2}
              title="Could not load documents"
              description={error instanceof Error ? error.message : 'An unexpected error occurred.'}
            />
          )}

          {!isLoading && !isError && filtered.length === 0 && (
            <EmptyState
              icon={FileSearch}
              title={
                documents && documents.length > 0
                  ? 'No documents match your filters'
                  : 'No documents yet'
              }
              description={
                documents && documents.length > 0
                  ? 'Try a different search term or status filter.'
                  : 'Upload a PDF above to get started.'
              }
            />
          )}

          {!isLoading && !isError && filtered.length > 0 && (
            <div className="w-full min-w-0 overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Name</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="hidden px-3 py-2 font-medium sm:table-cell">Chunks</th>
                    <th className="hidden px-3 py-2 font-medium md:table-cell">Pages</th>
                    <th className="hidden px-3 py-2 font-medium md:table-cell">Size</th>
                    <th className="hidden px-3 py-2 font-medium lg:table-cell">Uploaded</th>
                    <th className="px-3 py-2 text-right font-medium">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((document) => (
                    <DocumentRow key={document.document_id} document={document} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
