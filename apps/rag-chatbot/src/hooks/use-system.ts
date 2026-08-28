import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

export function useCapabilities() {
  return useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities, staleTime: 60_000 });
}

export function useSystemStatus() {
  return useQuery({
    queryKey: ['system-status'],
    queryFn: api.systemStatus,
    refetchInterval: 10_000,
  });
}
