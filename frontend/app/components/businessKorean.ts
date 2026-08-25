export function businessKorean(value: unknown): string {
  return String(value ?? "").split("·").join(", ");
}

export function businessKoreanJson(value: unknown): string {
  return businessKorean(JSON.stringify(value, null, 2));
}
