export type Validator<T = unknown> = (value: T) => string | null;

export const validators = {
  required: (value: unknown): string | null => {
    if (value === null || value === undefined) return 'Required';
    if (typeof value === 'string' && !value.trim()) return 'Required';
    return null;
  },

  maxLength: (max: number): Validator<string> => {
    return (value: string): string | null => {
      if (!value) return null;
      return value.length <= max ? null : `Max ${max} characters`;
    };
  },

  json: (value: string): string | null => {
    if (!value.trim()) return null;
    try {
      JSON.parse(value);
      return null;
    } catch {
      return 'Invalid JSON';
    }
  },

  compose: <T>(...validators: Validator<T>[]): Validator<T> => {
    return (value: T): string | null => {
      for (const validator of validators) {
        const error = validator(value);
        if (error) return error;
      }
      return null;
    };
  },
};

export function validateField<T>(value: T, ...validators: Validator<T>[]): string | null {
  for (const validator of validators) {
    const error = validator(value);
    if (error) return error;
  }
  return null;
}
