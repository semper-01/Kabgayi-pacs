import { createBasicAuthorization, request } from "./client";
import type { StudyPage } from "../types/study";

export async function authenticate(username: string, password: string): Promise<string> {
  const authorization = createBasicAuthorization(username, password);
  await request<StudyPage>("/api/studies/?limit=1&offset=0", authorization, {}, false);
  return authorization;
}
