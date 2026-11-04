import { describe, it, expect, vi } from 'vitest';
import { validators, validateField, type Validator } from '../validation';

describe.each([
  { name: 'compose', create: validators.compose },
  {
    name: 'validateField',
    create: <T>(...checks: Validator<T>[]) => (value: T) => validateField(value, ...checks),
  },
])('$name execution', ({ create }) => {
  it('runs lazily in order and stops at the first truthy error', () => {
    const value = { id: 'original' };
    const first = vi.fn<Validator<typeof value>>(() => null);
    const empty = vi.fn<Validator<typeof value>>(() => '');
    const failing = vi.fn<Validator<typeof value>>(() => 'First error');
    const skipped = vi.fn<Validator<typeof value>>(() => {
      throw new Error('This validator must not run');
    });

    const validate = create(first, empty, failing, skipped);
    for (const check of [first, empty, failing, skipped]) {
      expect(check).not.toHaveBeenCalled();
    }

    expect(validate(value)).toBe('First error');
    for (const check of [first, empty, failing]) {
      expect(check).toHaveBeenCalledExactlyOnceWith(value);
      expect(check.mock.calls[0][0]).toBe(value);
    }
    expect(first.mock.invocationCallOrder[0]).toBeLessThan(empty.mock.invocationCallOrder[0]);
    expect(empty.mock.invocationCallOrder[0]).toBeLessThan(failing.mock.invocationCallOrder[0]);
    expect(skipped).not.toHaveBeenCalled();
  });

  it('returns null when no validators are supplied', () => {
    expect(create()('anything')).toBeNull();
  });
});

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
