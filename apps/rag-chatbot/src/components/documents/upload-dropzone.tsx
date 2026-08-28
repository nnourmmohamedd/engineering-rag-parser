import { UploadCloud } from 'lucide-react';
import { useCallback, useId, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useUploadDocument } from '@/hooks/use-documents';
import { useCapabilities } from '@/hooks/use-system';
import { cn, formatBytes } from '@/lib/utils';

/**
 * Drag-and-drop + file-picker upload. Accepts a queue of files (one request
 * per file, in parallel) and lets the user pick the parser profile before
 * sending -- profiles come from the backend's /capabilities, never hard-coded.
 */
export function UploadDropzone() {
  const { data: capabilities } = useCapabilities();
  const upload = useUploadDocument();
  const [isDragging, setIsDragging] = useState(false);
  const [parserProfile, setParserProfile] = useState('default');
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const profileId = useId();

  const acceptedExtensions = useMemo(
    () => capabilities?.accepted_extensions ?? ['.pdf'],
    [capabilities?.accepted_extensions],
  );
  const maxBytes = capabilities?.max_upload_bytes ?? 100 * 1024 * 1024;

  const submitFiles = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`;
        if (!acceptedExtensions.includes(extension)) continue; // surfaced by the backend's own rejection too
        if (file.size === 0 || file.size > maxBytes) continue;
        upload.mutate({ file, parserProfile });
      }
    },
    [acceptedExtensions, maxBytes, parserProfile, upload],
  );

  return (
    <div className="space-y-3">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload documents. Drop files here or press Enter to browse."
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          submitFiles(event.dataTransfer.files);
        }}
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors',
          isDragging ? 'border-primary bg-accent' : 'border-border hover:border-primary/50',
        )}
      >
        <UploadCloud className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium">Drag and drop a PDF here, or click to browse</p>
        <p className="text-xs text-muted-foreground">
          {acceptedExtensions.join(', ')} only, up to {formatBytes(maxBytes)} per file
        </p>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={acceptedExtensions.join(',')}
          multiple
          className="sr-only"
          onChange={(event) => {
            if (event.target.files) submitFiles(event.target.files);
            event.target.value = '';
          }}
        />
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <label htmlFor={profileId} className="text-sm text-muted-foreground">
            Parser profile
          </label>
          <Select value={parserProfile} onValueChange={setParserProfile}>
            <SelectTrigger id={profileId} className="w-52">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(capabilities?.parser_profiles ?? []).map((profile) => (
                <SelectItem key={profile.id} value={profile.id} title={profile.description}>
                  {profile.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
          Browse files
        </Button>
      </div>
    </div>
  );
}
