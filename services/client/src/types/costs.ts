export interface CostReport {
  provider: string;
  period_start: string;
  period_end: string;
  currency: string;
  total: string | null;
  estimated: boolean;
  scope: string;
  fetched_at: string;
  data_through?: string | null;
  cost_basis: string;
  daily: { label: string; amount: string }[];
  breakdown: { label: string; amount: string }[];
  usage: { label: string; amount: string; unit: string }[];
  notes: string[];
  coverage_start?: string | null;
}

export interface CostResponse {
  state: string;
  report: CostReport | null;
  error?: { code: string; message: string } | null;
  message?: string;
  next_refresh_at?: string | null;
}
