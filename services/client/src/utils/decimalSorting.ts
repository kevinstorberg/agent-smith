interface Decimal {
  readonly sign: -1 | 0 | 1;
  readonly digits: string;
  readonly magnitude: bigint;
}

export function parseDecimal(value: string): Decimal | null {
  const match =
    /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(
      value.trim(),
    );
  if (!match) return null;
  const fraction = match[3] ?? match[4] ?? '';
  const digits = ((match[2] ?? '') + fraction).replace(/^0+/, '');
  if (!digits) return { sign: 0, digits: '0', magnitude: 0n };
  return {
    sign: match[1] === '-' ? -1 : 1,
    digits,
    magnitude:
      BigInt(match[5] ?? '0') - BigInt(fraction.length) + BigInt(digits.length),
  };
}

export function compareDecimalStrings(left: string, right: string): number {
  const a = parseDecimal(left);
  const b = parseDecimal(right);
  if (!a || !b)
    throw new Error('Decimal sorting requires two valid decimal strings.');
  if (a.sign !== b.sign) return a.sign - b.sign;
  if (a.sign === 0) return 0;
  if (a.magnitude !== b.magnitude)
    return (a.magnitude < b.magnitude ? -1 : 1) * a.sign;
  for (
    let index = 0;
    index < Math.max(a.digits.length, b.digits.length);
    index++
  ) {
    const first = a.digits[index] ?? '0';
    const second = b.digits[index] ?? '0';
    if (first !== second) return (first < second ? -1 : 1) * a.sign;
  }
  return 0;
}
