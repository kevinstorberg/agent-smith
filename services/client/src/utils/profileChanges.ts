import type { ProfileRevision } from '../api';
import { PROFILE_METADATA_FIELDS, PROFILE_SECTIONS } from './profileFields';

interface Change { key: string; label: string; before: string; after: string }
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): string => value == null ? '' : Array.isArray(value) ? value.filter(item => typeof item === 'string').join(', ') : typeof value === 'boolean' ? value ? 'Yes' : 'No' : typeof value === 'string' || typeof value === 'number' ? String(value) : '';

export function profileChanges(revision: ProfileRevision): { fields: Change[]; evidence: string | null; relationships: boolean } {
  const fields: Change[] = [];
  for (const [field, change] of Object.entries(revision.changes)) {
    if (field === 'section_notes' || field === 'metadata') {
      const labels = field === 'section_notes' ? PROFILE_SECTIONS : [...PROFILE_METADATA_FIELDS.map(({ key, label }) => [key, label] as const), ['other', 'Other'] as const];
      const before = object(change.before), after = object(change.after);
      for (const [key, label] of labels) {
        if (text(before[key]) !== text(after[key])) fields.push({ key: `${field}.${key}`, label, before: text(before[key]), after: text(after[key]) });
      }
    } else if (field.startsWith('section_notes.')) {
      const label = PROFILE_SECTIONS.find(([key]) => key === field.split('.')[1])?.[1];
      if (label) fields.push({ key: field, label, before: text(change.before), after: text(change.after) });
    } else if (field === 'section_evidence') {
      for (const [key, label] of PROFILE_SECTIONS) {
        const before = object(object(change.before)[key]).human === true;
        const after = object(object(change.after)[key]).human === true;
        if (before !== after) fields.push({ key: `ownership.${key}`, label: `${label} · Automatic updates`, before: before ? 'Protected by your edit' : 'Allowed', after: after ? 'Protected by your edit' : 'Allowed' });
      }
    } else if (field === 'relationships') {
      const snapshots = (value: unknown) => (Array.isArray(value) ? value : [value]).map(object).filter(edge => edge.id != null);
      const beforeRows = snapshots(change.before), afterRows = snapshots(change.after);
      const ids = new Set([...beforeRows, ...afterRows].map(edge => edge.id));
      for (const id of ids) {
        const before = beforeRows.find(edge => edge.id === id) || {}, after = afterRows.find(edge => edge.id === id) || {};
        const context = after.id ? after : before;
        const prefix = context.subject_name && context.target_name ? `${text(context.subject_name)} → ${text(context.target_name)} · ` : '';
        for (const [key, label] of [['label', 'Relationship label'], ['notes', 'Relationship assessment']]) {
          if (text(before[key]) !== text(after[key])) fields.push({ key: `relationships.${String(id)}.${key}`, label: `${prefix}${label}`, before: text(before[key]), after: text(after[key]) });
        }
        const protectedBefore = object(before.analysis_evidence).human === true, protectedAfter = object(after.analysis_evidence).human === true;
        if (protectedBefore !== protectedAfter) fields.push({ key: `relationships.${String(id)}.ownership`, label: `${prefix}Automatic updates`, before: protectedBefore ? 'Protected by your edit' : 'Allowed', after: protectedAfter ? 'Protected by your edit' : 'Allowed' });
        const status = (value: Record<string, unknown>) => value.id == null ? 'Not linked' : value.dismissed ? 'Removed' : 'Active';
        if (status(before) !== status(after)) fields.push({ key: `relationships.${String(id)}.status`, label: `${prefix}Relationship status`, before: status(before), after: status(after) });
      }
    } else {
      const label = ({ display_name: 'Name', email: 'Primary email', identity_scope: 'Identity matching', nicknames: 'Nicknames', tags: 'Tags', starred: 'Starred', deleted: 'Deleted' } as Record<string, string>)[field];
      if (label) fields.push({ key: field, label, before: text(change.before), after: text(change.after) });
      if (field === 'emails') {
        const added = object(change.after).added;
        fields.push({ key: field, label: 'Linked emails', before: text(change.before), after: text(Array.isArray(added) ? added : change.after) });
      }
    }
  }
  const delta = object(revision.changes.claims?.after);
  const counts = (['added', 'changed', 'removed'] as const).flatMap(key => Array.isArray(delta[key]) && delta[key].length ? [`${delta[key].length} ${key}`] : []);
  return { fields, evidence: revision.changes.claims ? counts.join(', ') || 'Supporting observations updated' : null, relationships: Boolean(revision.changes.relationships) };
}
