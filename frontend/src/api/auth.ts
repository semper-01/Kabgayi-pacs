import { createBasicAuthorization, request } from "./client";

export interface AuthenticatedUser {
  id: number;
  username: string;
  email: string;
  account_type: "staff" | "administrator";
  is_active: boolean;
}

export async function authenticate(
  username: string,
  password: string,
): Promise<{ authorization: string; user: AuthenticatedUser }> {
  const authorization = createBasicAuthorization(username, password);
  const user = await request<AuthenticatedUser>(
    "/api/auth/session/",
    authorization,
    {},
    false,
  );
  return { authorization, user };
}
