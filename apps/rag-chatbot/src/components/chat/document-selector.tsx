import { FileText } from 'lucide-react';

import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { useDocuments } from '@/hooks/use-documents';
import { truncateMiddle } from '@/lib/utils';

interface DocumentSelectorProps {
  selected: string[];
  onChange: (ids: string[]) => void;
}

/**
 * Only READY documents are selectable -- a processing or failed document
 * cannot answer a question, so it is shown but disabled rather than hidden,
 * so the user understands why it's unavailable.
 */
export function DocumentSelector({ selected, onChange }: DocumentSelectorProps) {
  const { data: documents, isLoading } = useDocuments();
  const readyDocuments = (documents ?? []).filter((d) => d.status === 'READY');
  const unavailableCount = (documents?.length ?? 0) - readyDocuments.length;

  const toggle = (id: string, checked: boolean) => {
    onChange(checked ? [...selected, id] : selected.filter((existing) => existing !== id));
  };

  if (isLoading) {
    return <p className="p-3 text-xs text-muted-foreground">Loading documents…</p>;
  }

  if (readyDocuments.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-4 text-center">
        <FileText className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
        <p className="text-xs text-muted-foreground">
          No documents are ready yet. Upload and process a document first.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between px-1 pb-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Select documents ({selected.length} selected)
        </span>
        {selected.length > 0 && (
          <button
            type="button"
            className="text-xs text-primary underline-offset-2 hover:underline"
            onClick={() => onChange([])}
          >
            Clear
          </button>
        )}
      </div>
      <ul className="max-h-56 space-y-0.5 overflow-y-auto" role="group" aria-label="Documents">
        {readyDocuments.map((document) => {
          const checkboxId = `doc-select-${document.document_id}`;
          return (
            <li
              key={document.document_id}
              className="flex items-center gap-2 rounded-md px-1 py-1.5 hover:bg-accent/50"
            >
              <Checkbox
                id={checkboxId}
                checked={selected.includes(document.document_id)}
                onCheckedChange={(checked) => toggle(document.document_id, checked === true)}
              />
              <Label
                htmlFor={checkboxId}
                className="min-w-0 flex-1 cursor-pointer truncate text-sm font-normal"
              >
                {truncateMiddle(document.display_name, 40)}
              </Label>
            </li>
          );
        })}
      </ul>
      {unavailableCount > 0 && (
        <p className="px-1 pt-1 text-xs text-muted-foreground">
          {unavailableCount} document{unavailableCount === 1 ? '' : 's'} not yet ready and
          unavailable for selection.
        </p>
      )}
    </div>
  );
}
