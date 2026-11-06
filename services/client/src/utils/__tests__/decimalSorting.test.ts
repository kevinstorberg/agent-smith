import { expect, it } from 'vitest';
import { compareDecimalStrings, parseDecimal } from '../decimalSorting';
it.each([
  ['2', '10', -1],
  ['-10', '-2', -1],
  ['0', '-0', 0],
  ['0.000001', '0.0000009', 1],
  ['9007199254740993', '9007199254740992', 1],
  ['1.000000000000000001', '1', 1],
  ['1e100000000000000000000', '9e99999999999999999999', 1],
  ['1e-100000000000000000000', '9e-100000000000000000001', 1],
  ['001.2300', '123e-2', 0],
  ['-.5', '-0.5000', 0],
  ['+2.', '2e0', 0],
  ['-1e9', '-999999999', -1],
])('compares %s and %s without floating-point rounding', (a, b, result) => {
  expect(Math.sign(compareDecimalStrings(a, b))).toBe(result);
  expect(Math.sign(compareDecimalStrings(b, a))).toBe(
    result === 0 ? 0 : -result,
  );
});
it.each(['Unavailable', 'NaN', 'Infinity', '', '1.2.3', '--3', '2e', '0x10'])(
  'rejects unavailable or malformed decimal %s',
  (value) => expect(parseDecimal(value)).toBeNull(),
);
