import type { Health } from "../types";

export function backendProblem(health: Health): string | null {
  if (health.api_contract === 3 && !health.restart_required) return null;
  return health.hosted
    ? "The interface and server versions differ. Reload after the server update finishes."
    : "The local server is running an older version of Kaizen. Stop the existing kaizen serve process, start it again, then reload this page.";
}
