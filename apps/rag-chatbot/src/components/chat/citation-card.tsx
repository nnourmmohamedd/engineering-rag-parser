import { FileWarning, Quote } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Citation } from '@/lib/types';

/**
 * One citation, expandable to show its supporting quote and full provenance
 * (source file, page, section, chunk id) -- everything needed to
 * independently verify the claim it backs.
 */
export function CitationCard({ citation }: { citation: Citation }) {
  const [expanded, setExpanded] = useState(false);
  const panelId = `citation-panel-${citation.citation_id}`;

  return (
    <div className="rounded-md border bg-card text-sm">
      <Button
        variant="ghost"
        className="h-auto w-full justify-start gap-2 rounded-md px-3 py-2 text-left font-normal"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={panelId}
      >
        <Badge variant="outline" className="shrink-0">
          [{citation.citation_id}]
        </Badge>
        <span className="min-w-0 flex-1 truncate">
          {citation.source_filename ?? 'Unknown source'}
          {citation.page_numbers.length > 0 && ` · p.${citation.page_numbers.join(', ')}`}
        </span>
        {!citation.source_available && (
          <Badge variant="warning" className="shrink-0">
            <FileWarning className="h-3 w-3" aria-hidden="true" /> Deleted
          </Badge>
        )}
      </Button>

      {expanded && (
        <div id={panelId} className="space-y-2 border-t px-3 py-3 text-xs">
          {!citation.source_available && (
            <p className="flex items-center gap-1.5 rounded-md bg-warning/10 p-2 text-warning">
              <FileWarning className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              The source document has since been deleted. This citation is preserved unchanged from
              when the answer was generated.
            </p>
          )}
          {citation.section_title && <Row label="Section" value={citation.section_title} />}
          {citation.chunk_id && <Row label="Chunk ID" value={citation.chunk_id} mono />}
          {citation.supporting_quote && (
            <div>
              <p className="mb-1 flex items-center gap-1 font-medium text-muted-foreground">
                <Quote className="h-3 w-3" aria-hidden="true" /> Supporting text
              </p>
              <blockquote className="rounded-md bg-muted p-2 italic text-foreground">
                "{citation.supporting_quote}"
              </blockquote>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? 'font-mono' : ''}>{value}</span>
    </div>
  );
}
