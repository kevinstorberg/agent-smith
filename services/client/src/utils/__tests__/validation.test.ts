import { describe, it, expect } from 'vitest';
import { validators, validateField } from '../validation';

describe('validators', () => {
  describe('required', () => {
    it('returns null for non-empty string', () => {
      expect(validators.required('hello')).toBeNull();
    });

    it('returns error for empty string', () => {
      expect(validators.required('')).toBe('Required');
    });

    it('returns error for whitespace', () => {
      expect(validators.required('   ')).toBe('Required');
    });

    it('returns error for null', () => {
      expect(validators.required(null)).toBe('Required');
    });

    it('returns error for undefined', () => {
      expect(validators.required(undefined)).toBe('Required');
    });
  });

  describe('maxLength', () => {
    it('returns null for string within limit', () => {
      const validator = validators.maxLength(10);
      expect(validator('hello')).toBeNull();
    });

    it('returns null for string at limit', () => {
      const validator = validators.maxLength(5);
      expect(validator('hello')).toBeNull();
    });

    it('returns error for string over limit', () => {
      const validator = validators.maxLength(5);
      expect(validator('hello world')).toBe('Max 5 characters');
    });

    it('returns null for empty string', () => {
      const validator = validators.maxLength(5);
      expect(validator('')).toBeNull();
    });
  });

  describe('json', () => {
    it('returns null for valid JSON', () => {
      expect(validators.json('{"key": "value"}')).toBeNull();
    });

    it('returns null for valid JSON array', () => {
      expect(validators.json('[1, 2, 3]')).toBeNull();
    });

    it('returns error for invalid JSON', () => {
      expect(validators.json('{invalid}')).toBe('Invalid JSON');
    });

    it('returns null for empty string', () => {
      expect(validators.json('')).toBeNull();
    });

    it('returns null for whitespace', () => {
      expect(validators.json('   ')).toBeNull();
    });
  });

  describe('compose', () => {
    it('returns null when all validators pass', () => {
      const validator = validators.compose(
        validators.required,
        validators.maxLength(10)
      );
      expect(validator('hello')).toBeNull();
    });

    it('returns first error when validator fails', () => {
      const validator = validators.compose(
        validators.required,
        validators.maxLength(3)
      );
      expect(validator('')).toBe('Required');
    });

    it('returns second error when first passes', () => {
      const validator = validators.compose(
        validators.required,
        validators.maxLength(3)
      );
      expect(validator('hello')).toBe('Max 3 characters');
    });
  });
});

describe('validateField', () => {
  it('returns null when all validators pass', () => {
    expect(validateField('hello', validators.required, validators.maxLength(10))).toBeNull();
  });

  it('returns first error when validator fails', () => {
    expect(validateField('', validators.required, validators.maxLength(10))).toBe('Required');
  });

  it('returns second error when first passes', () => {
    expect(validateField('hello world', validators.required, validators.maxLength(5))).toBe('Max 5 characters');
  });
});
