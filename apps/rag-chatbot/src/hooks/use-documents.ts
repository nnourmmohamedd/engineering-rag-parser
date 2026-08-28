import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { ApiError, api } from '@/lib/api';

export const documentKeys = {
  all: ['documents'] as const,
  detail: (id: string) => ['documents', id] as const,
  preview: (id: string) => ['documents', id, 'preview'] as const,
};

export function useDocuments() {
  return useQuery({
    queryKey: documentKeys.all,
    queryFn: api.listDocuments,
    // Documents transition through processing stages; poll while something
    // is active so the list reflects reality without a live subscription
    // per row (the document detail page uses SSE for finer-grained progress).
    refetchInterval: (query) => {
      const documents = query.state.data;
      const hasActive = documents?.some(
        (d) => d.status === 'PROCESSING' || d.status === 'UPLOADED',
      );
      return hasActive ? 1_500 : false;
    },
  });
}

export function useDocument(documentId: string | null) {
  return useQuery({
    queryKey: documentId ? documentKeys.detail(documentId) : ['documents', 'none'],
    queryFn: () => api.getDocument(documentId as string),
    enabled: documentId !== null,
  });
}

export function useDocumentPreview(documentId: string | null) {
  return useQuery({
    queryKey: documentId ? documentKeys.preview(documentId) : ['documents', 'none', 'preview'],
    queryFn: () => api.previewDocument(documentId as string),
    enabled: documentId !== null,
  });
}

function describeError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  return fallback;
}

export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, parserProfile }: { file: File; parserProfile: string }) =>
      api.uploadDocument(file, parserProfile),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: documentKeys.all });
      if (result.duplicate_of) {
        toast.info(
          `"${result.document.display_name}" already exists — using the existing document.`,
        );
      } else {
        toast.success(`"${result.document.display_name}" uploaded and queued for processing.`);
      }
    },
    onError: (error, variables) => {
      toast.error(
        `Could not upload "${variables.file.name}": ${describeError(error, 'Upload failed.')}`,
      );
    },
  });
}

export function useReprocessDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, parserProfile }: { documentId: string; parserProfile?: string }) =>
      api.reprocessDocument(documentId, parserProfile),
    onSuccess: (_job, variables) => {
      queryClient.invalidateQueries({ queryKey: documentKeys.all });
      queryClient.invalidateQueries({ queryKey: documentKeys.detail(variables.documentId) });
      toast.success('Reprocessing started.');
    },
    onError: (error) => toast.error(describeError(error, 'Could not start reprocessing.')),
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => api.deleteDocument(documentId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: documentKeys.all });
      toast.success(`"${result.display_name}" was deleted.`);
    },
    onError: (error) => toast.error(describeError(error, 'Could not delete the document.')),
  });
}

export function useRetryJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.retryJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentKeys.all });
      toast.success('Retrying.');
    },
    onError: (error) => toast.error(describeError(error, 'Could not retry.')),
  });
}

export function useCancelJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.cancelJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentKeys.all });
      toast.info('Cancellation requested.');
    },
    onError: (error) => toast.error(describeError(error, 'Could not cancel.')),
  });
}
