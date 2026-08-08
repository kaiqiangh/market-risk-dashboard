import { useTranslation } from "react-i18next";
import { useDataset, type UseDatasetResult } from "@/hooks/useDataset";
import type { AnalysisDataset, FactLayer } from "@/schemas";
import {
  deriveAnalysisPresentation,
  type AnalysisPresentation,
} from "@/lib/analysisState";

interface AnalysisPairQueries {
  current: UseDatasetResult<AnalysisDataset>;
  alternate: UseDatasetResult<AnalysisDataset>;
  facts: UseDatasetResult<FactLayer>;
}

export interface UseAnalysisPairResult {
  presentation: AnalysisPresentation;
  isLoading: boolean;
  queries: AnalysisPairQueries;
}

/** Fetch both language briefs and the fact layer before exposing a homepage brief. */
export function useAnalysisPair(): UseAnalysisPairResult {
  const { i18n } = useTranslation();
  const locale = i18n.language === "en" ? "en" : "zh-CN";
  const alternateLocale = locale === "en" ? "zh-CN" : "en";
  const current = useDataset<AnalysisDataset>("analysis", { lang: locale });
  const alternate = useDataset<AnalysisDataset>("analysis", { lang: alternateLocale });
  const facts = useDataset<FactLayer>("factlayer");
  const isLoading = current.isLoading || alternate.isLoading || facts.isLoading;

  return {
    presentation: deriveAnalysisPresentation({
      current: current.data,
      alternate: alternate.data,
      facts: facts.data,
      currentError: current.error,
      alternateError: alternate.error,
      factsError: facts.error,
    }),
    isLoading,
    queries: { current, alternate, facts },
  };
}
