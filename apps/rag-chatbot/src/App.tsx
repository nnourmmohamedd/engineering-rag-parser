import { QueryClientProvider } from '@tanstack/react-query';
import { Navigate, Route, HashRouter as Router, Routes } from 'react-router-dom';
import { Toaster } from 'sonner';

import { AppShell } from '@/components/layout/app-shell';
import { ErrorBoundary } from '@/components/layout/error-boundary';
import { useTheme } from '@/hooks/use-theme';
import { queryClient } from '@/lib/query-client';
import { ChatPage } from '@/pages/chat-page';
import { DocumentDetailPage } from '@/pages/document-detail-page';
import { DocumentsPage } from '@/pages/documents-page';
import { SystemPage } from '@/pages/system-page';

function ToasterWithTheme() {
  const { resolvedTheme } = useTheme();
  return <Toaster theme={resolvedTheme} position="bottom-right" richColors closeButton />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <ErrorBoundary>
          <AppShell>
            <Routes>
              <Route path="/" element={<ChatPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
              <Route path="/system" element={<SystemPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AppShell>
        </ErrorBoundary>
        <ToasterWithTheme />
      </Router>
    </QueryClientProvider>
  );
}
