import type { JobConfig } from '../../api';
import { jobFixture } from './jobFixture';

const base = jobFixture.configs![0];
export const jobConfigSortingRows: JobConfig[] = [
  {
    ...base,
    id: 30,
    device: 'Zulu',
    repo: 'repo-b',
    enabled: true,
    exclude: false,
  },
  {
    ...base,
    id: 20,
    device: 'alpha',
    repo: 'Repo-A',
    enabled: false,
    exclude: true,
  },
  {
    ...base,
    id: 10,
    device: 'ALPHA',
    repo: 'repo-c',
    enabled: true,
    exclude: false,
  },
];
