const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let unauthorizedHandler: (() => void) | undefined;

export function setUnauthorizedHandler(handler: (() => void) | undefined): void {
  unauthorizedHandler = handler;
}

export function createBasicAuthorization(username: string, password: string): string {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return `Basic ${btoa(binary)}`;
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export async function request<T>(
  path: string,
  authorization: string,
  init: RequestInit = {},
  handleUnauthorized = true,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: {
        Accept: "application/json",
        ...init.headers,
        Authorization: authorization,
      },
      credentials: "same-origin",
    });
  } catch {
    throw new Error("Unable to connect to the PACS server. Check your connection and try again.");
  }

  if (response.status === 401) {
    if (handleUnauthorized) unauthorizedHandler?.();
    throw new ApiError("Your authentication has expired. Please sign in again.", 401);
  }
  if (response.status === 403) {
    throw new ApiError("You are not authorized to access this information.", 403);
  }
  if (!response.ok) {
    throw new ApiError(
      await responseErrorMessage(response, "The request could not be completed. Please try again."),
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

export async function requestFile(
  path: string,
  authorization: string,
  fallback = "Export failed. Please try again.",
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      headers: {
        Accept: "*/*",
        Authorization: authorization,
      },
      credentials: "same-origin",
    });
  } catch {
    throw new Error("Unable to connect to the PACS server. Check your connection and try again.");
  }

  if (response.status === 401) {
    unauthorizedHandler?.();
    throw new ApiError("Your authentication has expired. Please sign in again.", 401);
  }
  if (response.status === 403) {
    throw new ApiError("You are not authorized to export this study.", 403);
  }
  if (!response.ok) {
    throw new ApiError(await responseErrorMessage(response, fallback), response.status);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filenameMatch = disposition.match(/filename="([^"]+)"/i);
  const filename = filenameMatch?.[1]?.replace(/[\\/:*?"<>|]/g, "_") || "study-export";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function responseErrorMessage(response: Response, fallback: string): Promise<string> {
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.includes("application/json")) return fallback;
  try {
    const payload: unknown = await response.json();
    if (typeof payload !== "object" || payload === null) return fallback;
    const errors = payload as Record<string, unknown>;
    for (const key of ["error", "detail", "validation_errors"]) {
      const value = errors[key];
      if (typeof value === "string" && value.trim()) return value;
      if (Array.isArray(value)) {
        const messages = value.filter((item): item is string => typeof item === "string");
        if (messages.length) return messages.join(" ");
      }
    }
    const fieldErrors = errors.errors;
    if (typeof fieldErrors === "object" && fieldErrors !== null) {
      const messages = Object.values(fieldErrors).flatMap((value) =>
        typeof value === "string"
          ? [value]
          : Array.isArray(value)
            ? value.filter((item): item is string => typeof item === "string")
            : [],
      );
      if (messages.length) return messages.join(" ");
    }
  } catch {
    return fallback;
  }
  return fallback;
}

export function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.status === 401 ? "Authentication failed. Check your username and password." : error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}
