import { request } from "./client";

const GRANT_PATH = "/api/viewer-access/grant/";
const REVOKE_PATH = "/api/viewer-access/revoke/";

export interface ViewerGrant {
  expires_in: number;
}

export function issueViewerGrant(authorization: string): Promise<ViewerGrant> {
  return request<ViewerGrant>(GRANT_PATH, authorization, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export function revokeViewerGrant(
  authorization: string,
  keepalive = false,
): Promise<{ revoked: boolean }> {
  return request<{ revoked: boolean }>(REVOKE_PATH, authorization, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
    keepalive,
  });
}
