import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import type { Capabilities } from '@/lib/types';
import { renderWithProviders } from '@/test/render';
import { UploadDropzone } from './upload-dropzone';

const capabilities: Capabilities = {
  version: '1.0.0',
  parser_profiles: [{ id: 'default', label: 'Default', description: 'Balanced settings.' }],
  retrieval_modes: ['vector'],
  default_retrieval_mode: 'vector',
  accepted_extensions: ['.pdf'],
  accepted_media_types: ['application/pdf'],
  max_upload_bytes: 10_000_000,
  max_pages: 2000,
  provider: 'ollama',
  model_tag: 'qwen3:4b',
  model_digest: 'abc',
  generation_is_cpu_bound: true,
};

describe('UploadDropzone', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('advertises only PDF, sourced from the backend capabilities', async () => {
    vi.spyOn(api, 'capabilities').mockResolvedValue(capabilities);
    renderWithProviders(<UploadDropzone />);

    await waitFor(() => expect(screen.getByText(/\.pdf only/)).toBeInTheDocument());
  });

  it('is reachable via the keyboard and opens the file picker on Enter', async () => {
    vi.spyOn(api, 'capabilities').mockResolvedValue(capabilities);
    const user = userEvent.setup();
    renderWithProviders(<UploadDropzone />);

    const dropzone = screen.getByRole('button', { name: /Upload documents/i });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');

    dropzone.focus();
    await user.keyboard('{Enter}');

    expect(clickSpy).toHaveBeenCalled();
  });

  it('submits a valid PDF selected through the file input', async () => {
    vi.spyOn(api, 'capabilities').mockResolvedValue(capabilities);
    const uploadSpy = vi.spyOn(api, 'uploadDocument').mockResolvedValue({
      document: {
        document_id: 'd1',
        display_name: 'a.pdf',
        status: 'UPLOADED',
        parser_profile: 'default',
        byte_size: 10,
        page_count: null,
        total_chunks: null,
        warning_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        sha256: 'x'.repeat(64),
      },
      job: null,
      duplicate_of: null,
    });

    const user = userEvent.setup();
    renderWithProviders(<UploadDropzone />);
    await waitFor(() => screen.getByText(/\.pdf only/));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3])], 'a.pdf', { type: 'application/pdf' });
    await user.upload(input, file);

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledWith(file, 'default'));
  });

  it('does not submit a file with an unsupported extension', async () => {
    vi.spyOn(api, 'capabilities').mockResolvedValue(capabilities);
    const uploadSpy = vi.spyOn(api, 'uploadDocument');
    const user = userEvent.setup();
    renderWithProviders(<UploadDropzone />);
    await waitFor(() => screen.getByText(/\.pdf only/));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' });
    await user.upload(input, file);

    expect(uploadSpy).not.toHaveBeenCalled();
  });
});
