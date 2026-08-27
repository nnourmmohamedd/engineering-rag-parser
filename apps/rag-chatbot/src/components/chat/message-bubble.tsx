import { AlertOctagon, Check, Copy, ShieldQuestion, User } from 'lucide-react';
import { useState } from 'react';
import Markdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Message } from '@/lib/types';
import { cn, formatDuration } from '@/lib/utils';
import { CitationCard } from './citation-card';

const STATUS_COPY: Record<string, { label: string; tone: 'success' | 'warning' | 'destructive' }> =
  {
    answered: { label: 'Grounded answer', tone: 'success' },
    insufficient_evidence: { label: 'Insufficient evidence — refused', tone: 'warning' },
    validation_failed: { label: 'Failed grounding validation', tone: 'destructive' },
    generation_failed: { label: 'Generation failed', tone: 'destructive' },
    failed: { label: 'Could not answer', tone: 'destructive' },
  };

export function MessageBubble({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access denied: silently no-op rather than showing an alarming error.
    }
  };

  if (isUser) {
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[85%] rounded-lg rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground sm:max-w-[70%]">
          {message.content}
        </div>
        <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary">
          <User className="h-3.5 w-3.5" aria-hidden="true" />
        </div>
      </div>
    );
  }

  const statusInfo = message.status ? STATUS_COPY[message.status] : undefined;
  const isRefusalOrFailure = message.status !== 'answered';
  const totalTime = Object.values(message.stage_timings).reduce((sum, v) => sum + v, 0);

  return (
    <div className="flex gap-2">
      <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        {isRefusalOrFailure ? (
          <ShieldQuestion className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <span className="text-[10px] font-bold">AI</span>
        )}
      </div>
      <div className="min-w-0 max-w-[90%] flex-1 space-y-2 sm:max-w-[80%]">
        {statusInfo && (
          <Badge
            variant={statusInfo.tone}
            className={cn(statusInfo.tone === 'destructive' && 'gap-1')}
          >
            {statusInfo.tone === 'destructive' && (
              <AlertOctagon className="h-3 w-3" aria-hidden="true" />
            )}
            {statusInfo.label}
          </Badge>
        )}

        <div
          className={cn(
            'rounded-lg rounded-tl-sm border px-4 py-3 text-sm',
            statusInfo?.tone === 'destructive'
              ? 'border-destructive/30 bg-destructive/5'
              : statusInfo?.tone === 'warning'
                ? 'border-warning/30 bg-warning/5'
                : 'bg-card',
          )}
        >
          {message.content ? (
            <div className="prose-engineering">
              <Markdown rehypePlugins={[rehypeSanitize]}>{message.content}</Markdown>
            </div>
          ) : (
            <p className="italic text-muted-foreground">No answer text was produced.</p>
          )}
        </div>

        {message.content && (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={copy} className="h-7 gap-1.5 text-xs">
              {copied ? (
                <Check className="h-3 w-3" aria-hidden="true" />
              ) : (
                <Copy className="h-3 w-3" aria-hidden="true" />
              )}
              {copied ? 'Copied' : 'Copy answer'}
            </Button>
            {totalTime > 0 && (
              <span className="text-xs text-muted-foreground">{formatDuration(totalTime)}</span>
            )}
            {message.model_tag && (
              <span className="hidden text-xs text-muted-foreground sm:inline">
                · {message.model_tag}
              </span>
            )}
          </div>
        )}

        {message.citations.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Sources ({message.citations.length})
            </p>
            {message.citations.map((citation) => (
              <CitationCard key={citation.citation_id} citation={citation} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
