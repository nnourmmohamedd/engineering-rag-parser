import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useCapabilities, useSystemStatus } from '@/hooks/use-system';

export function SystemPage() {
  const { data: capabilities, isLoading: loadingCapabilities } = useCapabilities();
  const { data: status, isLoading: loadingStatus } = useSystemStatus();

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">System status</h1>
        <p className="text-sm text-muted-foreground">
          This is local, single-user software with no authentication. It binds to your machine only
          (127.0.0.1) — see the security documentation before exposing it on a network.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Dependencies</CardTitle>
          <CardDescription>Ollama, the vector index and the keyword index.</CardDescription>
        </CardHeader>
        <CardContent>
          {loadingStatus ? (
            <div className="space-y-2" aria-hidden="true">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : (
            <ul className="divide-y">
              {status?.dependencies.map((dependency) => (
                <li
                  key={dependency.name}
                  className="flex items-center justify-between py-2 text-sm"
                >
                  <span className="flex items-center gap-2 font-medium capitalize">
                    {dependency.available ? (
                      <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
                    ) : (
                      <XCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
                    )}
                    {dependency.name}
                  </span>
                  <span className="text-muted-foreground">{dependency.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Documents</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <StatRow label="Total" value={status?.documents_total} loading={loadingStatus} />
            <StatRow label="Ready" value={status?.documents_ready} loading={loadingStatus} />
            <StatRow label="Active jobs" value={status?.jobs_active} loading={loadingStatus} />
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Worker</span>
              {loadingStatus ? (
                <Skeleton className="h-5 w-16" />
              ) : (
                <Badge variant={status?.worker_running ? 'success' : 'destructive'}>
                  {status?.worker_running ? 'Running' : 'Stopped'}
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Model</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {loadingCapabilities ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Provider</span>
                  <span className="font-medium capitalize">{capabilities?.provider}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Model</span>
                  <span className="font-mono text-xs">{capabilities?.model_tag ?? 'unknown'}</span>
                </div>
                {capabilities?.generation_is_cpu_bound && (
                  <div className="mt-2 flex items-start gap-2 rounded-md bg-warning/10 p-2 text-xs text-warning">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <span>
                      Generation runs locally on CPU. A single answer can take several minutes on
                      modest hardware.
                    </span>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Application data</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="cursor-help border-b border-dotted">Data directory</span>
              </TooltipTrigger>
              <TooltipContent>
                Shown in abbreviated form; the full machine path is never exposed.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          : <span className="font-mono text-xs">{status?.data_root_label ?? '—'}</span>
        </CardContent>
      </Card>
    </div>
  );
}

function StatRow({ label, value, loading }: { label: string; value?: number; loading: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      {loading ? (
        <Skeleton className="h-5 w-8" />
      ) : (
        <span className="font-medium">{value ?? '—'}</span>
      )}
    </div>
  );
}
