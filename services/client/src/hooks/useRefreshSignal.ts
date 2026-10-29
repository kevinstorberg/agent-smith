import { useEffect, useRef } from 'react';

export function useRefreshSignal(signal: number | undefined, refresh: () => void | Promise<void>) {
  const previous = useRef(signal);
  useEffect(() => {
    if (signal !== previous.current) {
      previous.current = signal;
      refresh();
    }
  }, [signal, refresh]);
}
