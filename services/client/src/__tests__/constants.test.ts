import { describe, it, expect } from 'vitest';
import {
  isMarkdownType, toggleArrayItem, formatError,
  isValidName, nameError, isValidRepo, MAX_NAME_LENGTH,
} from '../constants';

describe('isMarkdownType', () => {
  it('returns true for rule', () => expect(isMarkdownType('rule')).toBe(true));
  it('returns true for skill', () => expect(isMarkdownType('skill')).toBe(true));
  it('returns false for tool', () => expect(isMarkdownType('tool')).toBe(false));
  it('returns false for hook', () => expect(isMarkdownType('hook')).toBe(false));
  it('returns false for empty', () => expect(isMarkdownType('')).toBe(false));
});

describe('toggleArrayItem', () => {
  it('adds item when absent', () => {
    expect(toggleArrayItem(['a', 'b'], 'c')).toEqual(['a', 'b', 'c']);
  });
  it('removes item when present', () => {
    expect(toggleArrayItem(['a', 'b', 'c'], 'b')).toEqual(['a', 'c']);
  });
  it('adds to empty array', () => {
    expect(toggleArrayItem([], 'x')).toEqual(['x']);
  });
  it('works with numbers', () => {
    expect(toggleArrayItem([1, 2], 2)).toEqual([1]);
  });
});

describe('formatError', () => {
  it('extracts message from Error', () => {
    expect(formatError(new Error('boom'))).toBe('boom');
  });
  it('converts string to string', () => {
    expect(formatError('oops')).toBe('oops');
  });
  it('converts null', () => {
    expect(formatError(null)).toBe('null');
  });
  it('converts number', () => {
    expect(formatError(42)).toBe('42');
  });
});

describe('isValidName', () => {
  it('accepts lowercase with underscores', () => expect(isValidName('my_rule')).toBe(true));
  it('accepts single letter', () => expect(isValidName('a')).toBe(true));
  it('accepts letter and digits', () => expect(isValidName('rule1')).toBe(true));
  it('rejects uppercase', () => expect(isValidName('MyRule')).toBe(false));
  it('rejects starting with digit', () => expect(isValidName('1rule')).toBe(false));
  it('rejects hyphens', () => expect(isValidName('my-rule')).toBe(false));
  it('rejects spaces', () => expect(isValidName('my rule')).toBe(false));
  it('rejects over max length', () => expect(isValidName('a'.repeat(MAX_NAME_LENGTH + 1))).toBe(false));
  it('accepts exactly max length', () => expect(isValidName('a'.repeat(MAX_NAME_LENGTH))).toBe(true));
});

describe('nameError', () => {
  it('returns null for valid name', () => expect(nameError('my_rule')).toBeNull());
  it('returns required for empty', () => expect(nameError('')).toBe('Name is required.'));
  it('returns required for whitespace', () => expect(nameError('   ')).toBe('Name is required.'));
  it('returns pattern error for invalid chars', () => {
    expect(nameError('My-Rule')).toMatch(/lowercase/);
  });
  it('returns length error for too long', () => {
    expect(nameError('a'.repeat(MAX_NAME_LENGTH + 1))).toMatch(/characters or fewer/);
  });
});

describe('isValidRepo', () => {
  it('accepts wildcard', () => expect(isValidRepo('*')).toBe(true));
  it('accepts absolute path', () => expect(isValidRepo('/home/user/proj')).toBe(true));
  it('rejects relative path', () => expect(isValidRepo('relative/path')).toBe(false));
  it('rejects empty string', () => expect(isValidRepo('')).toBe(false));
});
