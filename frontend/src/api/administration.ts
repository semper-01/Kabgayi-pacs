import { request, requestFile } from "./client";

export interface AdminUser {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  account_type: "staff" | "administrator";
  is_active: boolean;
  date_joined: string;
  last_login: string | null;
}

export interface ActivityEvent {
  id: string;
  event_type: string;
  label: string;
  outcome: string;
  username: string;
  source_ip: string | null;
  details: Record<string, string>;
  created_at: string;
}

export interface Machine {
  id: number;
  display_name: string;
  modality: string;
  remote_ae_title: string;
  ip_address: string;
  port: number;
  enabled: boolean;
  registration: string;
  connectivity: "unknown" | "healthy" | "warning" | "offline";
  last_connectivity_check: string | null;
  ingestion: string;
}

export interface ServiceHealth {
  overall: "healthy" | "warning" | "offline";
  checked_at: string;
  services: { name: string; status: string; message: string }[];
}

export interface ConfigurationValues {
  ae_title: string;
  dicom_port: number;
  lan_ip: string;
  updated_at: string;
}

export interface ConfigurationChange {
  id: number;
  change_type: string;
  proposed_values: Record<string, string | number | boolean>;
  state: "edit" | "validated" | "reviewed" | "applied" | "cancelled";
  validation_errors: string[];
  restart_required: boolean;
  restart_confirmed: boolean;
  created_by: string;
  reviewed_by: string | null;
  created_at: string;
}

export interface ImportValidation {
  files: {
    filename: string;
    valid: boolean;
    duplicates: { type: string; id: string }[];
  }[];
  duplicate_count: number;
  imported: false;
}

export interface ImportResult {
  summary: {
    filename: string;
    result: "imported" | "skipped_duplicate";
    instance_id?: string;
    study_id?: string;
  }[];
  verification: { verified_count: number; failed: boolean };
}

export function getOverview(authorization: string) {
  return request<{
    total_studies: number | null;
    users: { total: number; staff: number; administrators: number; active: number; inactive: number };
    active_viewing_sessions: number;
    recent_activity: ActivityEvent[];
    service_health: ServiceHealth;
  }>("/api/admin/overview/", authorization);
}

export function getUsers(authorization: string) {
  return request<AdminUser[]>("/api/admin/users/", authorization);
}

export function createUser(
  authorization: string,
  values: { username: string; email: string; account_type: "staff" | "administrator"; password: string },
) {
  return request<Pick<AdminUser, "id" | "username" | "account_type" | "is_active">>(
    "/api/admin/users/",
    authorization,
    json(values),
  );
}

export function setUserActive(authorization: string, id: number, is_active: boolean) {
  return request<{ id: number; is_active: boolean }>(
    `/api/admin/users/${id}/`,
    authorization,
    json({ is_active }, "PATCH"),
  );
}

export function resetUserPassword(authorization: string, id: number, new_password: string) {
  return request<{ id: number; password_reset: boolean }>(
    `/api/admin/users/${id}/`,
    authorization,
    json({ new_password }),
  );
}

export type ActivityCategory = "all" | "login" | "viewing" | "export";

export function getActivity(authorization: string, category: ActivityCategory = "all") {
  return request<{ results: ActivityEvent[]; audit_gaps: string[] }>(
    `/api/admin/activity/?category=${category}`,
    authorization,
  );
}

export function downloadActivity(authorization: string, category: ActivityCategory) {
  return requestFile(
    `/api/admin/activity/export/?category=${category}`,
    authorization,
    "Unable to download audit activity.",
  );
}

export function getServiceHealth(authorization: string) {
  return request<ServiceHealth>("/api/admin/service-health/", authorization);
}

export function getMachines(authorization: string) {
  return request<Machine[]>("/api/admin/machines/", authorization);
}

export function stageMachineChange(
  authorization: string,
  change_type: "machine_create" | "machine_update",
  values: Record<string, string | number | boolean>,
) {
  return createConfigurationChange(authorization, change_type, values);
}

export function testMachineConnectivity(authorization: string, id: number) {
  return request<Machine & { connectivity_test: string; message: string }>(
    `/api/admin/machines/${id}/connectivity/`,
    authorization,
    json({}),
  );
}

export function deleteMachine(authorization: string, id: number) {
  return request<void>(
    `/api/admin/machines/${id}/`,
    authorization,
    json({ confirm: true }, "DELETE"),
  );
}

export function checkMachineIdentity(
  authorization: string,
  remote_ae_title: string,
  ip_address: string,
) {
  return request<{ registered: boolean; enabled: boolean; ingestion: string }>(
    "/api/admin/machines/ingestion-check/",
    authorization,
    json({ remote_ae_title, ip_address }),
  );
}

export function getMachineStudies(authorization: string, id: number) {
  return request<{
    results: { study_id: string; validated_at: string }[];
  }>(`/api/admin/machines/${id}/studies/`, authorization);
}

export function verifyMachineStudies(authorization: string, id: number, study_ids: string[]) {
  return request<{ associated_studies: string[]; rejected_studies: string[] }>(
    `/api/admin/machines/${id}/verify-studies/`,
    authorization,
    json({ study_ids }),
  );
}

export function getNetworkConfiguration(authorization: string) {
  return request<ConfigurationValues>("/api/admin/network-configuration/", authorization);
}

export function createConfigurationChange(
  authorization: string,
  change_type: "network" | "machine_create" | "machine_update",
  values: Record<string, string | number | boolean>,
) {
  return request<ConfigurationChange>(
    "/api/admin/configuration-changes/",
    authorization,
    json({ change_type, values }),
  );
}

export function validateConfigurationChange(authorization: string, id: number) {
  return request<ConfigurationChange>(
    `/api/admin/configuration-changes/${id}/validate/`,
    authorization,
    json({}),
  );
}

export function cancelConfigurationChange(authorization: string, id: number) {
  return request<ConfigurationChange>(
    `/api/admin/configuration-changes/${id}/cancel/`,
    authorization,
    json({}),
  );
}

export function reviewConfigurationChange(authorization: string, id: number) {
  return request<ConfigurationChange>(
    `/api/admin/configuration-changes/${id}/review/`,
    authorization,
    json({}),
  );
}

export function applyConfigurationChange(
  authorization: string,
  id: number,
  confirm_restart = false,
) {
  return request<ConfigurationChange & { restart_performed: false; message: string }>(
    `/api/admin/configuration-changes/${id}/apply/`,
    authorization,
    json({ confirm_restart }),
  );
}

export function validateDicomImport(authorization: string, files: File[]) {
  return request<ImportValidation>(
    "/api/admin/dicom-import/validate/",
    authorization,
    { method: "POST", body: multipart(files) },
  );
}

export function importDicom(
  authorization: string,
  files: File[],
  duplicate_policy?: "skip" | "overwrite",
) {
  const data = multipart(files);
  if (duplicate_policy) data.set("duplicate_policy", duplicate_policy);
  return request<ImportResult>("/api/admin/dicom-import/import/", authorization, {
    method: "POST",
    body: data,
  });
}

function json(body: unknown, method = "POST"): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function multipart(files: File[]): FormData {
  const data = new FormData();
  files.forEach((file) => data.append("files", file, file.name));
  return data;
}
