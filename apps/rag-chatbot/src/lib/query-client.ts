import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Local-only backend on the same machine: retries mostly just delay
      // showing a real error (e.g. "Ollama not running") to the user.
      retry: false,
      staleTime: 5_000,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
});
