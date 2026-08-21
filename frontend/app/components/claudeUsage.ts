export const CLAUDE_USAGE_CONFIRMATION =
  "이 옵션을 켜면 서버에 설정된 Claude API 키로 Claude API를 호출합니다. 입력 및 출력 토큰이 사용되어 비용이 발생할 수 있습니다. 계속하시겠습니까?";

export function nextClaudeUsage(
  enabled: boolean,
  confirmUsage: (message: string) => boolean = (message) => window.confirm(message),
): boolean {
  return enabled && confirmUsage(CLAUDE_USAGE_CONFIRMATION);
}
