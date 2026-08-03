import { useQuery } from "@tanstack/react-query";
import type { z } from "zod";
import { datasetClient, type DatasetOptions } from "@/lib/api";
import { staleTimeFor } from "@/lib/freshness";
import type { DatasetKey } from "@/schemas";

/**
 * useDataset：TanStack Query 包装（架构 §3.6 / §4.3）。
 * - 内部：DatasetClient.fetch → Zod parse；失败抛 SchemaError → 页面渲染 ErrorState。
 * - schema 可选：历史切片（history/{key}/{slice}.json 为纯数组）与元数据需显式传入，
 *   否则默认用注册表 envelope schema。
 * - queryKey 包含 lang/slice/schema 形态，避免不同解析方式互相污染缓存。
 * - staleTime 按数据集 freshness 语义设置（Fix P2-10：market 短、macro/calendar 长，
 *   而非一律 60s；与 config/sources.yaml 期望频率对齐）。
 */
export interface UseDatasetResult<T> {
  data: T | undefined;
  status: "pending" | "success" | "error";
  error: Error | null;
  isError: boolean;
  isLoading: boolean;
  isSuccess: boolean;
  /** 重新拉取（ErrorState 重试用）。 */
  refetch: () => Promise<unknown>;
}

export function useDataset<T>(
  key: DatasetKey,
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
