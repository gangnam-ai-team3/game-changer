const DAY_MS = 86_400_000;

function utcDate(time: number) {
  return new Date(time).toISOString().slice(0, 10);
}

export function corpusDemoDates(now = new Date()) {
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return {
    cutoffOn: utcDate(today + DAY_MS),
    startsOn: utcDate(today + 2 * DAY_MS),
    endsOn: utcDate(today + 9 * DAY_MS),
  };
}

export function isFutureUtcDate(value: string, now = new Date()) {
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && value > utcDate(today);
}
