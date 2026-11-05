import { api } from '../api';
import { useApiRead } from './useApiRead';
import { usePolling } from './usePolling';

export function useActionItemProjects(paused = false) {
  const read = useApiRead(api.actionItemProjects.list);
  usePolling(() => read.refresh({ showLoading: false }), {
    enabled: !paused && !read.loading,
  });
  return read;
}
