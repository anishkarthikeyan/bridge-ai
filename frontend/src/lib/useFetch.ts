import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

interface UseFetchOptions {
  /** Poll interval in ms. Omitted/undefined = fetch once. The interval is cleared on
   * unmount, so polling only ever runs while the consuming page is mounted (spec §13: "Only
   * poll when the Case page is active"). */
  pollMs?: number;
}

interface UseFetchResult<T> {
  data: T | null;
  /** Only set for the initial load — a poll tick that fails leaves the last good data on
   * screen rather than replacing it with an error (a transient network blip shouldn't blank
   * out a working view). */
  error: string | null;
  isLoading: boolean;
  refetch: () => void;
}

/** One small hook backing every page's data loading + optional live polling, so no page
 * hand-rolls its own fetch/loading/error bookkeeping (spec §17: "Do not scatter fetch()
 * calls throughout components"). `key` resets state when it changes (e.g. a case id from
 * the route) so switching cases doesn't briefly show the previous case's data. */
export function useFetch<T>(
  fetcher: () => Promise<T>,
  key: string,
  options: UseFetchOptions = {},
): UseFetchResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    setIsLoading(true);

    async function load(isInitial: boolean) {
      try {
        const result = await fetcherRef.current();
        if (cancelled) return;
        setData(result);
        if (isInitial) setError(null);
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Something went wrong.";
        if (isInitial) setError(message);
      } finally {
        if (!cancelled && isInitial) setIsLoading(false);
      }
    }

    load(true);

    let intervalId: ReturnType<typeof setInterval> | undefined;
    if (options.pollMs) {
      intervalId = setInterval(() => load(false), options.pollMs);
    }

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, options.pollMs, generation]);

  return { data, error, isLoading, refetch: () => setGeneration((g) => g + 1) };
}
