import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const SAMPLE_PDF = path.join(__dirname, 'sample.pdf');
