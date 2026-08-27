import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { ApiError, api } from '@/lib/api';
import type { RetrievalMode } from '@/lib/types';

export const conversationKeys = {
  all: ['conversations'] as const,
  detail: (id: string) => ['conversations', id] as const,
};

export function useConversations() {
  return useQuery({ queryKey: conversationKeys.all, queryFn: api.listConversations });
}

export function useConversation(conversationId: string | null) {
  return useQuery({
    queryKey: conversationId ? conversationKeys.detail(conversationId) : ['conversations', 'none'],
    queryFn: () => api.getConversation(conversationId as string),
    enabled: conversationId !== null,
  });
}

function describeError(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
    onError: (error) => toast.error(describeError(error, 'Could not create the conversation.')),
  });
}

export function useUpdateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      conversationId,
      ...payload
    }: {
      conversationId: string;
      title?: string;
      selected_document_ids?: string[];
      retrieval_mode?: RetrievalMode;
    }) => api.updateConversation(conversationId, payload),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: conversationKeys.all });
      queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(variables.conversationId),
      });
    },
    onError: (error) => toast.error(describeError(error, 'Could not update the conversation.')),
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) => api.deleteConversation(conversationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: conversationKeys.all });
      toast.success('Conversation deleted.');
    },
    onError: (error) => toast.error(describeError(error, 'Could not delete the conversation.')),
  });
}

export function useAsk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      conversationId,
      ...payload
    }: {
      conversationId: string;
      query: string;
      selected_document_ids: string[];
      retrieval_mode: RetrievalMode;
      top_k?: number | null;
    }) => api.ask(conversationId, payload),
    onSuccess: (_messages, variables) => {
      queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(variables.conversationId),
      });
      queryClient.invalidateQueries({ queryKey: conversationKeys.all });
    },
    onError: (error) => toast.error(describeError(error, 'The question could not be answered.')),
  });
}
