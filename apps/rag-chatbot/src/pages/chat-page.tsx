import { AlertTriangle, Loader2, Menu, MessageSquare, Send, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { ConversationSidebar } from '@/components/chat/conversation-sidebar';
import { DocumentSelector } from '@/components/chat/document-selector';
import { MessageBubble } from '@/components/chat/message-bubble';
import { RetrievalModeSelect } from '@/components/chat/retrieval-mode-select';
import { EmptyState } from '@/components/layout/empty-state';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import {
  useConversation,
  useCreateConversation,
  useUpdateConversation,
  useAsk,
} from '@/hooks/use-conversations';
import { useCapabilities } from '@/hooks/use-system';
import type { RetrievalMode } from '@/lib/types';
import { cn } from '@/lib/utils';

export function ChatPage() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mobileOptionsOpen, setMobileOptionsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>('vector');

  const { data: capabilities } = useCapabilities();
  const { data: conversation } = useConversation(conversationId);
  const createConversation = useCreateConversation();
  const updateConversation = useUpdateConversation();
  const ask = useAsk();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (conversation) {
      setSelectedDocuments(conversation.conversation.selected_document_ids);
      setRetrievalMode(conversation.conversation.retrieval_mode as RetrievalMode);
    }
  }, [conversation?.conversation.conversation_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation?.messages.length, ask.isPending]);

  const ensureConversation = async (): Promise<string> => {
    if (conversationId) return conversationId;
    const created = await createConversation.mutateAsync({});
    setConversationId(created.conversation_id);
    return created.conversation_id;
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || selectedDocuments.length === 0 || ask.isPending) return;

    const id = await ensureConversation();
    setQuery('');
    await ask.mutateAsync({
      conversationId: id,
      query: trimmed,
      selected_document_ids: selectedDocuments,
      retrieval_mode: retrievalMode,
    });
  };

  const canSubmit = query.trim().length > 0 && selectedDocuments.length > 0 && !ask.isPending;
  const messages = conversation?.messages ?? [];

  return (
    <div className="flex h-full">
      {/* Desktop conversation sidebar */}
      <ConversationSidebar
        activeId={conversationId}
        onSelect={(id) => setConversationId(id)}
        className="hidden w-60 shrink-0 border-r md:flex"
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar: conversation drawer + options drawer toggles */}
        <div className="flex items-center justify-between border-b px-3 py-2 md:hidden">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="Open conversations"
          >
            <Menu className="h-4 w-4" aria-hidden="true" /> Conversations
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setMobileOptionsOpen(true)}
            aria-label="Open document selection and retrieval options"
          >
            Options ({selectedDocuments.length})
          </Button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          {!conversationId || messages.length === 0 ? (
            <EmptyState
              icon={MessageSquare}
              title="Ask a question about your engineering documents"
              description="Select one or more ready documents on the right, choose a retrieval mode, and ask a question. Answers are grounded with inspectable citations, or the system will explicitly refuse."
              className="mx-auto mt-8 max-w-md"
            />
          ) : (
            <div className="mx-auto max-w-3xl space-y-5">
              {messages.map((message) => (
                <MessageBubble key={message.message_id} message={message} />
              ))}
              {ask.isPending && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  Retrieving context and generating a grounded answer
                  {capabilities?.generation_is_cpu_bound &&
                    ' — this can take several minutes on this machine'}
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="border-t bg-card p-3 sm:p-4">
          <form onSubmit={handleSubmit} className="mx-auto max-w-3xl space-y-2">
            {selectedDocuments.length === 0 && (
              <p className="flex items-center gap-1.5 text-xs text-warning">
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                Select at least one document before asking a question.
              </p>
            )}
            <div className="flex items-end gap-2">
              <Textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    handleSubmit(event);
                  }
                }}
                placeholder="Ask a question about the selected documents…"
                rows={2}
                className="min-h-0 resize-none"
                aria-label="Question"
              />
              <Button type="submit" disabled={!canSubmit} aria-label="Send question">
                {ask.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="h-4 w-4" aria-hidden="true" />
                )}
              </Button>
            </div>
          </form>
        </div>
      </div>

      {/* Desktop options panel */}
      <aside className="hidden w-72 shrink-0 flex-col gap-4 overflow-y-auto border-l bg-card p-4 lg:flex">
        <OptionsPanel
          selectedDocuments={selectedDocuments}
          onSelectedDocumentsChange={(ids) => {
            setSelectedDocuments(ids);
            if (conversationId)
              updateConversation.mutate({ conversationId, selected_document_ids: ids });
          }}
          retrievalMode={retrievalMode}
          onRetrievalModeChange={(mode) => {
            setRetrievalMode(mode);
            if (conversationId) updateConversation.mutate({ conversationId, retrieval_mode: mode });
          }}
          availableModes={capabilities?.retrieval_modes ?? ['vector']}
        />
      </aside>

      {/* Mobile drawers */}
      {mobileSidebarOpen && (
        <MobileDrawer title="Conversations" onClose={() => setMobileSidebarOpen(false)}>
          <ConversationSidebar
            activeId={conversationId}
            onSelect={(id) => {
              setConversationId(id);
              setMobileSidebarOpen(false);
            }}
          />
        </MobileDrawer>
      )}
      {mobileOptionsOpen && (
        <MobileDrawer title="Documents & retrieval" onClose={() => setMobileOptionsOpen(false)}>
          <div className="p-3">
            <OptionsPanel
              selectedDocuments={selectedDocuments}
              onSelectedDocumentsChange={setSelectedDocuments}
              retrievalMode={retrievalMode}
              onRetrievalModeChange={setRetrievalMode}
              availableModes={capabilities?.retrieval_modes ?? ['vector']}
            />
          </div>
        </MobileDrawer>
      )}
    </div>
  );
}

interface OptionsPanelProps {
  selectedDocuments: string[];
  onSelectedDocumentsChange: (ids: string[]) => void;
  retrievalMode: RetrievalMode;
  onRetrievalModeChange: (mode: RetrievalMode) => void;
  availableModes: RetrievalMode[];
}

function OptionsPanel({
  selectedDocuments,
  onSelectedDocumentsChange,
  retrievalMode,
  onRetrievalModeChange,
  availableModes,
}: OptionsPanelProps) {
  return (
    <>
      <div>
        <h2 className="mb-2 text-sm font-semibold">Retrieval mode</h2>
        <RetrievalModeSelect
          value={retrievalMode}
          onChange={onRetrievalModeChange}
          availableModes={availableModes}
        />
      </div>
      <Card className="p-2">
        <DocumentSelector selected={selectedDocuments} onChange={onSelectedDocumentsChange} />
      </Card>
    </>
  );
}

function MobileDrawer({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex lg:hidden"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        className={cn('relative ml-auto flex h-full w-80 max-w-[85vw] flex-col bg-card shadow-xl')}
      >
        <div className="flex items-center justify-between border-b p-3">
          <span className="text-sm font-semibold">{title}</span>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={`Close ${title}`}>
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
