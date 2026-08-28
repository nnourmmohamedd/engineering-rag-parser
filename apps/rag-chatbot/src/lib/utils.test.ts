import { describe, expect, it } from 'vitest';

import { formatBytes, formatDuration, stageLabel, truncateMiddle } from './utils';

describe('formatBytes', () => {
  it('formats zero', () => expect(formatBytes(0)).toBe('0 B'));
  it('formats bytes', () => expect(formatBytes(512)).toBe('512 B'));
  it('formats kilobytes', () => expect(formatBytes(2048)).toBe('2 KB'));
  it('formats megabytes with one decimal under 10', () =>
    expect(formatBytes(1_500_000)).toBe('1.4 MB'));
  it('formats large megabytes without a decimal', () =>
    expect(formatBytes(50_000_000)).toBe('48 MB'));
});

describe('formatDuration', () => {
  it('formats sub-second durations in ms', () => expect(formatDuration(0.25)).toBe('250 ms'));
  it('formats seconds', () => expect(formatDuration(4.2)).toBe('4.2 s'));
  it('formats minutes and seconds', () => expect(formatDuration(125)).toBe('2m 5s'));
  it('formats hours and minutes', () => expect(formatDuration(3725)).toBe('1h 2m'));
  it('returns an em dash for invalid input', () => {
    expect(formatDuration(-1)).toBe('—');
    expect(formatDuration(NaN)).toBe('—');
  });
});

describe('truncateMiddle', () => {
  it('leaves short text untouched', () =>
    expect(truncateMiddle('short.pdf', 40)).toBe('short.pdf'));
  it('truncates long text keeping both ends visible', () => {
    const long = 'a'.repeat(60) + '.pdf';
    const result = truncateMiddle(long, 20);
    expect(result.length).toBeLessThanOrEqual(21);
    expect(result).toContain('…');
    expect(result.startsWith('a')).toBe(true);
  });
});

describe('stageLabel', () => {
  it('maps known stages to readable labels', () => {
    expect(stageLabel('PARSING')).toBe('Parsing document');
    expect(stageLabel('VECTOR_INDEXING')).toBe('Indexing (vector)');
  });
  it('falls back to the raw value for an unknown stage', () => {
    expect(stageLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW');
  });
});
