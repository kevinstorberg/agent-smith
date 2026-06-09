import { useState } from 'react';
import { useNotification } from '../context/useNotification';
import { formatError } from '../constants';

interface UseApiMutationOptions<TData, TVariables extends unknown[]> {
  mutationFn: (...args: TVariables) => Promise<TData>;
  onSuccess?: (data: TData) => void;
  onError?: (error: Error) => void;
}

interface UseApiMutationReturn<TData, TVariables extends unknown[]> {
  mutate: (...args: TVariables) => Promise<void>;
  mutateAsync: (...args: TVariables) => Promise<TData>;
  loading: boolean;
  error: Error | null;
  reset: () => void;
}

export function useApiMutation<TData = unknown, TVariables extends unknown[] = unknown[]>(
  options: UseApiMutationOptions<TData, TVariables>
): UseApiMutationReturn<TData, TVariables> {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const { notify } = useNotification();

  const mutateAsync = async (...args: TVariables): Promise<TData> => {
    setLoading(true);
    setError(null);

    try {
      const data = await options.mutationFn(...args);
      options.onSuccess?.(data);
      return data;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);

      if (options.onError) {
        options.onError(error);
      } else {
        // Default error notification if no custom handler provided
        notify(formatError(err), 'error');
      }

      throw error;
    } finally {
      setLoading(false);
    }
  };

  const mutate = async (...args: TVariables): Promise<void> => {
    try {
      await mutateAsync(...args);
    } catch {
      // Error already handled in mutateAsync
    }
  };

  const reset = () => {
    setLoading(false);
    setError(null);
  };

  return {
    mutate,
    mutateAsync,
    loading,
    error,
    reset,
  };
}
