import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { api, ApiError } from '../api';
import type { MeetingAnalysisInput, MeetingAnalysisReceipt } from '../api';
import { usePolling } from './usePolling';

const MONITOR_MS = 30 * 60 * 1000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function useManualAnalysisRequest(onChanged: () => void) {
  const [params, setParams] = useSearchParams();
  const requestId = params.get('analysis');
  const [receipt, setReceipt] = useState<MeetingAnalysisReceipt | null>(null);
  const [frozen, setFrozen] = useState<MeetingAnalysisInput | null>(null);
  const [saving, setSaving] = useState(false);
  const [reading, setReading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const mounted = useRef(false);
  const writing = useRef<number | null>(null);
  const operation = useRef(0);
  const readVersion = useRef(0);
  const startedAt = useRef(0);
  const lastStatus = useRef<string | null>(null);
  const onChangedRef = useRef(onChanged);
  const setParamsRef = useRef(setParams);
  const liveId = useRef(requestId);
  useEffect(() => { onChangedRef.current = onChanged; }, [onChanged]);
  useEffect(() => { setParamsRef.current = setParams; }, [setParams]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const accept = useCallback((value: MeetingAnalysisReceipt) => {
    if (lastStatus.current !== value.status && (value.status === 'done' || value.status === 'failed')) onChangedRef.current();
    lastStatus.current = value.status;
    setReceipt(value);
  }, []);
  const refresh = useCallback(async (id = liveId.current) => {
    if (!id || !UUID.test(id)) return;
    const epoch = operation.current;
    const version = ++readVersion.current;
    const current = () => mounted.current && epoch === operation.current && version === readVersion.current && liveId.current === id;
    setReading(true);
    try {
      const value = await api.meetingAnalysis.progress(id);
      if (value.request_id !== id) throw new Error('The returned analysis request does not match this view.');
      if (!current()) return;
      accept(value); setNotice(null);
    } catch (error) {
      if (current()) setNotice(`Could not read analysis progress. ${error instanceof Error ? error.message : 'Try refreshing the status.'}`);
    } finally {
      if (current()) setReading(false);
    }
  }, [accept]);
  useEffect(() => {
    liveId.current = requestId;
    operation.current++; readVersion.current++; writing.current = null;
    setReceipt(null); setFrozen(null); setSaving(false); setReading(false); setNotice(null); setExpired(false);
    lastStatus.current = null; startedAt.current = Date.now();
    if (!requestId) return;
    if (!UUID.test(requestId)) { setNotice('This analysis request link is invalid.'); return; }
    refresh(requestId);
  }, [requestId, refresh]);
  const active = Boolean(receipt && !['done', 'failed'].includes(receipt.status));
  usePolling(() => {
    if (document.hidden || reading || saving) return;
    if (Date.now() - startedAt.current >= MONITOR_MS) { setExpired(true); return; }
    return refresh();
  }, { enabled: active && !expired, intervalMs: 3000 });

  const mutate = async (id: string, input: MeetingAnalysisInput | null) => {
    if (writing.current !== null) return;
    const epoch = ++operation.current;
    const viewId = liveId.current;
    const current = () => mounted.current && operation.current === epoch && liveId.current === viewId;
    writing.current = epoch; readVersion.current++;
    setReading(false); setSaving(true); setNotice(null); setFrozen(input);
    try {
      const value = await (input ? api.meetingAnalysis.request(input) : api.meetingAnalysis.resume(id));
      if (value.request_id !== id) throw new Error('The analysis receipt does not match this request.');
      if (!current()) return;
      if (input) {
        setReceipt(value); lastStatus.current = value.status; setFrozen(null);
        setParamsRef.current(previous => { const next = new URLSearchParams(previous); next.set('analysis', value.request_id); return next; }, { replace: true });
      } else accept(value);
      startedAt.current = Date.now(); setExpired(false); onChangedRef.current();
    } catch (error) {
      if (!current()) return;
      if (input) {
        if (error instanceof ApiError && [409, 422].includes(error.status)) {
          setFrozen(null);
          setNotice(`${error.message} Review the updated meeting selection before confirming again.`);
          onChangedRef.current();
        } else setNotice('The request result could not be read. Retry this same request to check whether it was accepted; it will not create another analysis pass.');
      } else setNotice(`${error instanceof Error ? error.message : 'Could not resume this analysis.'} Saved progress is retained.`);
    } finally {
      if (current()) { writing.current = null; setSaving(false); }
    }
  };
  const submit = (input: MeetingAnalysisInput) => mutate(input.request_id, input);
  const resume = () => receipt ? mutate(receipt.request_id, null) : Promise.resolve();
  const reset = () => {
    if (saving || frozen) return;
    operation.current++; readVersion.current++;
    setReceipt(null); setReading(false); setNotice(null); setExpired(false);
    setParams(previous => { const next = new URLSearchParams(previous); next.delete('analysis'); return next; }, { replace: true });
  };
  return { receipt, frozen, saving, reading, notice, expired, requestId,
    submit, resume, refresh: () => refresh(), reset };
}
