export const CLAUDE_USAGE_CONFIRMATION =
  "Claude API로 팀 에이전트 추가 검증을 실행합니다. 입력 및 출력 토큰이 사용되어 비용이 발생할 수 있습니다. 계속하시겠습니까?";

export function nextClaudeUsage(
  enabled: boolean,
  confirmUsage: (message: string) => boolean = (message) => window.confirm(message),
): boolean {
  return enabled && confirmUsage(CLAUDE_USAGE_CONFIRMATION);
}
