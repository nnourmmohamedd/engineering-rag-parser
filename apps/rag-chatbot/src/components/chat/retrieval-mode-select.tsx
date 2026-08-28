import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Info } from 'lucide-react';

import type { RetrievalMode } from '@/lib/types';

const MODE_DESCRIPTIONS: Record<RetrievalMode, string> = {
  vector: 'Semantic similarity search over embeddings. The default, balanced mode.',
  hybrid: 'Combines semantic search with keyword (BM25) matching for exact terms and identifiers.',
  'vector-rerank':
    'Semantic search, then a cross-encoder reranks the top candidates for precision.',
  'hybrid-rerank':
    'Keyword + semantic search, then cross-encoder reranking. Slowest, most thorough.',
};

const MODE_LABELS: Record<RetrievalMode, string> = {
  vector: 'Vector',
  hybrid: 'Hybrid',
  'vector-rerank': 'Vector + Rerank',
  'hybrid-rerank': 'Hybrid + Rerank',
};

interface RetrievalModeSelectProps {
  value: RetrievalMode;
  onChange: (mode: RetrievalMode) => void;
  availableModes: RetrievalMode[];
}

export function RetrievalModeSelect({ value, onChange, availableModes }: RetrievalModeSelectProps) {
  return (
    <div className="flex items-center gap-1.5">
      <Select value={value} onValueChange={(next) => onChange(next as RetrievalMode)}>
        <SelectTrigger aria-label="Retrieval mode" className="w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {availableModes.map((mode) => (
            <SelectItem key={mode} value={mode}>
              {MODE_LABELS[mode]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger aria-label={`About ${MODE_LABELS[value]} retrieval`}>
            <Info className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          </TooltipTrigger>
          <TooltipContent>{MODE_DESCRIPTIONS[value]}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
