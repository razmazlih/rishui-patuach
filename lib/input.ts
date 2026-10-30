export function normalizePlate(value: string): string | null {
  if (value.length > 32) return null;
  const plate = value.replace(/[\s-]/g, '');
  return /^\d{7,8}$/.test(plate) ? plate : null;
}
export function dataMode(value = process.env.DATA_MODE): 'demo' | 'live' {
  if (value === 'demo' || value === 'live') return value;
  throw new Error('DATA_MODE must explicitly be demo or live');
}
export function sourceState(source: {availability: string; active_run_id: string | number | null; coverage: Record<string,unknown>; updated_at: string | Date}, found: boolean) {
  if (source.availability === 'blocked') return 'quality_failed';
  if (source.availability === 'unavailable') return 'unavailable';
  if (source.coverage?.covered === false) return 'not_covered';
  if (!source.active_run_id) return 'not_loaded';
  const asOf = typeof source.coverage?.as_of === 'string' ? source.coverage.as_of : null;
  const staleDays = typeof source.coverage?.stale_after_days === 'number' ? source.coverage.stale_after_days : 180;
  if (asOf && Date.now() - new Date(asOf).getTime() > 1000 * 60 * 60 * 24 * staleDays) return 'stale';
  return found ? 'available' : 'not_found';
}
