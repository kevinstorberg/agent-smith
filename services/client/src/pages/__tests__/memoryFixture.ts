import type { MemoryConfig } from '../../api';

export const offsetMemoryConfig: MemoryConfig = {
  listing: {
    mode: 'offset',
    source: 'test-offset',
    filters: true,
    sort_options: [
      'created_at_desc',
      'created_at_asc',
      'updated_at_desc',
      'updated_at_asc',
    ],
    total: true,
  },
  search: { max_candidates: 50 },
};

export const cursorMemoryConfig: MemoryConfig = {
  listing: {
    mode: 'cursor',
    source: 'test-index',
    filters: false,
    sort_options: ['id_asc'],
    total: false,
  },
  search: { max_candidates: 50 },
};
