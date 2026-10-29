export function parseTags(value: string): string[] {
  return [...new Set(value.split(',').map(tag => tag.trim()).filter(Boolean))];
}
