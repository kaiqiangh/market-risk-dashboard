import { useQuery } from "@tanstack/react-query";
import type { z } from "zod";
import { datasetClient, type DatasetOptions, type HistoryKey, type MetadataKey } from "@/lib/api";
import { staleTimeFor } from "@/lib/freshness";
import type { DatasetKey } from "@/schemas";

/**
 * useDataset: TanStack Query wrapper (architecture §3.6 / §4.3).
 * - Internally: DatasetClient.fetch → Zod parse; on failure throws SchemaError → page renders ErrorState.
 * - schema optional: history slices (history/{key}/{slice}.json are plain arrays) and metadata must be passed explicitly,
 *   otherwise the registry envelope schema is used by default.
 * - queryKey includes lang/slice/schema shape to avoid different parse modes polluting each other's cache.
 * - staleTime is set by dataset freshness semantics (Fix P2-10: short for market, long for macro/calendar,
 *   rather than always 60s; aligned with expected frequencies in config/sources.yaml).
 */
export interface UseDatasetResult<T> {
  data: T | undefined;
  status: "pending" | "success" | "error";
  error: Error | null;
  isError: boolean;
  isLoading: boolean;
  isSuccess: boolean;
  /** Refetch (used by ErrorState retry). */
  refetch: () => Promise<unknown>;
}

export function useDataset<T>(
  key: DatasetKey | HistoryKey | MetadataKey,
  opts: DatasetOptions = {},
  schema?: z.ZodTypeAny,
): UseDatasetResult<T> {
  const { lang, slice } = opts;
  const schemaKind = schema ? "custom" : "default";
  const queryKey = [key, lang ?? "none", slice ?? "latest", schemaKind] as const;

  return useQuery<unknown, Error, T>({
    queryKey,
    queryFn: () => datasetClient.fetch<T>(key, opts, schema),
    staleTime: staleTimeFor(key),
    retry: 1,
  });
}
