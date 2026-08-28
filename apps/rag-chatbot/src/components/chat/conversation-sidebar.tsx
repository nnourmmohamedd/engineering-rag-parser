import { MessageSquarePlus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
} from '@/hooks/use-conversations';
import { cn, formatDateTime, truncateMiddle } from '@/lib/utils';

interface ConversationSidebarProps {
  activeId: string | null;
  onSelect: (id: string) => void;
  className?: string;
}

export function ConversationSidebar({ activeId, onSelect, className }: ConversationSidebarProps) {
  const { data: conversations, isLoading } = useConversations();
  const create = useCreateConversation();
  const remove = useDeleteConversation();

  return (
    <div className={cn('flex flex-col', className)}>
      <div className="border-b p-3">
        <Button
          className="w-full justify-start"
          variant="outline"
          onClick={() =>
            create.mutate(
              {},
              { onSuccess: (conversation) => onSelect(conversation.conversation_id) },
            )
          }
          disabled={create.isPending}
        >
          <MessageSquarePlus className="h-4 w-4" aria-hidden="true" />
          New conversation
        </Button>
      </div>

      <nav aria-label="Conversations" className="flex-1 overflow-y-auto p-2">
        {isLoading && <p className="p-2 text-xs text-muted-foreground">Loading…</p>}
        {!isLoading && (conversations?.length ?? 0) === 0 && (
          <p className="p-2 text-xs text-muted-foreground">
            No conversations yet. Start one to ask a question.
          </p>
        )}
        <ul className="space-y-1">
          {conversations?.map((conversation) => (
            <li key={conversation.conversation_id}>
              <div
                className={cn(
                  'group flex items-center gap-1 rounded-md px-2 py-2 text-sm transition-colors',
                  conversation.conversation_id === activeId
                    ? 'bg-accent text-accent-foreground'
                    : 'hover:bg-accent/50',
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(conversation.conversation_id)}
                  className="min-w-0 flex-1 truncate text-left"
                  aria-current={conversation.conversation_id === activeId ? 'true' : undefined}
                >
                  <span className="block truncate font-medium">
                    {truncateMiddle(conversation.title || 'Untitled conversation', 32)}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {formatDateTime(conversation.updated_at)}
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                  aria-label={`Delete conversation "${conversation.title}"`}
                  onClick={() => remove.mutate(conversation.conversation_id)}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
