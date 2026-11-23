import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../../api";
import type { Execution } from "../../types";

/**
 * The sample's lab-execution state. Every action returns the full state
 * again, so the screen always redraws from what the server holds.
 */
export function useExecution(sampleId: number | string | undefined) {
  const [exec, setExec] = useState<Execution | null>(null);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    if (sampleId === undefined) return;
    try {
      setExec(await apiGet<Execution>(`/api/samples/${sampleId}/execution/`));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the step requirements.");
    }
  }, [sampleId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { exec, setExec, error, reload };
}
