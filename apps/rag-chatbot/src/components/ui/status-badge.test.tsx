import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DocumentStatusBadge, JobStateBadge } from './status-badge';

describe('DocumentStatusBadge', () => {
  it.each([
    ['UPLOADED', 'Uploaded'],
    ['PROCESSING', 'Processing'],
    ['READY', 'Ready'],
    ['FAILED', 'Failed'],
    ['INTERRUPTED', 'Interrupted'],
    ['DELETED', 'Deleted'],
  ] as const)('renders a readable label for %s', (status, label) => {
    render(<DocumentStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('pairs status text with an icon, not colour alone', () => {
    const { container } = render(<DocumentStatusBadge status="FAILED" />);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });
});

describe('JobStateBadge', () => {
  it.each([
    ['QUEUED', 'Queued'],
    ['RUNNING', 'Running'],
    ['READY', 'Complete'],
    ['FAILED', 'Failed'],
    ['CANCELLED', 'Cancelled'],
    ['INTERRUPTED', 'Interrupted'],
  ] as const)('renders a readable label for %s', (state, label) => {
    render(<JobStateBadge state={state} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
