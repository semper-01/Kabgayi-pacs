import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { getErrorMessage } from "../api/client";
import {
  applyConfigurationChange,
  cancelConfigurationChange,
  checkMachineIdentity,
  createConfigurationChange,
  createUser,
  deleteMachine,
  downloadActivity,
  getActivity,
  getMachines,
  getMachineStudies,
  getNetworkConfiguration,
  getOverview,
  getServiceHealth,
  getUsers,
  importDicom,
  resetUserPassword,
  reviewConfigurationChange,
  setUserActive,
  stageMachineChange,
  testMachineConnectivity,
  validateConfigurationChange,
  validateDicomImport,
  verifyMachineStudies,
  type ActivityEvent,
  type ActivityCategory,
  type AdminUser,
  type ConfigurationChange,
  type ConfigurationValues,
  type ImportValidation,
  type Machine,
  type ServiceHealth,
} from "../api/administration";
import { useAuth } from "../auth/AuthContext";

const sections = [
  "System Overview",
  "Users",
  "Activity",
  "Service Health",
  "Machine Management",
  "DICOM Import",
  "Network Configuration",
] as const;

type Section = (typeof sections)[number];

export function AdministrationPage() {
  const { authorization } = useAuth();
  const [section, setSection] = useState<Section>("System Overview");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof getOverview>> | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [activity, setActivity] = useState<Awaited<ReturnType<typeof getActivity>> | null>(null);
  const [activityCategory, setActivityCategory] = useState<ActivityCategory>("all");
  const [health, setHealth] = useState<ServiceHealth | null>(null);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [network, setNetwork] = useState<ConfigurationValues | null>(null);
  const [pendingChange, setPendingChange] = useState<ConfigurationChange | null>(null);
  const [editingMachine, setEditingMachine] = useState<Machine | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [importValidation, setImportValidation] = useState<ImportValidation | null>(null);
  const [importSummary, setImportSummary] = useState<string[]>([]);
  const [duplicateDecisionRequired, setDuplicateDecisionRequired] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importProgress, setImportProgress] = useState<{
    total: number;
    completed: number;
    succeeded: number;
    skipped: number;
    failed: number;
    currentFile: string;
  } | null>(null);

  const refresh = useCallback(async () => {
    if (!authorization) return;
    setLoading(true);
    setError("");
    try {
      if (section === "System Overview") setOverview(await getOverview(authorization));
      if (section === "Users") setUsers(await getUsers(authorization));
      if (section === "Activity") setActivity(await getActivity(authorization, activityCategory));
      if (section === "Service Health") setHealth(await getServiceHealth(authorization));
      if (section === "Machine Management") setMachines(await getMachines(authorization));
      if (section === "Network Configuration") {
        setNetwork(await getNetworkConfiguration(authorization));
      }
    } catch (loadError) {
      setError(getErrorMessage(loadError, "Unable to load administration data."));
    } finally {
      setLoading(false);
    }
  }, [activityCategory, authorization, section]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run<T>(operation: () => Promise<T>, success?: string): Promise<T | null> {
    setError("");
    setNotice("");
    try {
      const result = await operation();
      if (success) setNotice(success);
      await refresh();
      return result;
    } catch (operationError) {
      setError(getErrorMessage(operationError, "The operation could not be completed."));
      return null;
    }
  }

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authorization) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const result = await run(
      () =>
        createUser(authorization, {
          username: String(form.get("username") || "").trim(),
          email: String(form.get("email") || "").trim(),
          account_type: String(form.get("account_type")) as "staff" | "administrator",
          password: String(form.get("password") || ""),
        }),
      "User account created.",
    );
    if (result) formElement.reset();
  }

  async function changeUser(user: AdminUser) {
    if (!authorization) return;
    if (user.is_active) {
      await run(
        () => setUserActive(authorization, user.id, false),
        `${user.username} deactivated.`,
      );
      return;
    }
    await run(() => setUserActive(authorization, user.id, true), `${user.username} activated.`);
  }

  async function resetPassword(user: AdminUser) {
    if (!authorization) return;
    const newPassword = window.prompt(`Enter a new password for ${user.username}`);
    if (!newPassword) return;
    await run(
      () => resetUserPassword(authorization, user.id, newPassword),
      `Password reset for ${user.username}.`,
    );
  }

  async function testConnectivity(machine: Machine) {
    if (!authorization) return;
    const result = await run(
      () => testMachineConnectivity(authorization, machine.id),
      "Connectivity test completed. This does not verify DICOM ingestion.",
    );
    if (result && result.connectivity_test === "offline") {
      setNotice(result.message);
    }
  }

  async function applyStagedChange(change: ConfigurationChange) {
    if (!authorization) return;
    const confirmRestart = change.restart_required
      ? window.confirm(
          "A manual PACS restart will be required. The DICOM listener may be unavailable during restart. No restart will be performed automatically. Apply these settings?",
        )
      : false;
    if (change.restart_required && !confirmRestart) return;
    await run(
      () => applyConfigurationChange(authorization, change.id, confirmRestart),
      "Configuration change applied. No service was restarted.",
    );
    setPendingChange(null);
  }

  async function cancelStagedChange(change: ConfigurationChange) {
    if (!authorization) return;
    try {
      await cancelConfigurationChange(authorization, change.id);
      setPendingChange(null);
      setNotice("Unapplied configuration draft cancelled.");
      setError("");
      await refresh();
    } catch (cancelError) {
      setError(getErrorMessage(cancelError, "Unable to cancel configuration draft."));
    }
  }

  async function advanceChange(change: ConfigurationChange) {
    if (!authorization) return;
    setError("");
    try {
      if (change.state === "edit") {
        const validated = await validateConfigurationChange(authorization, change.id);
        setPendingChange(validated);
        if (validated.validation_errors.length) {
          setError(validated.validation_errors.join(" "));
          return;
        }
      } else if (change.state === "validated") {
        setPendingChange(await reviewConfigurationChange(authorization, change.id));
      } else if (change.state === "reviewed") {
        await applyStagedChange(change);
      }
      await refresh();
    } catch (stageError) {
      setError(getErrorMessage(stageError, "Configuration stage could not be completed."));
    }
  }

  async function saveNetwork(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authorization || !network) return;
    const form = new FormData(event.currentTarget);
    try {
      const change = await createConfigurationChange(authorization, "network", {
        ae_title: String(form.get("ae_title") || "").trim(),
        dicom_port: Number(form.get("dicom_port")),
        lan_ip: String(form.get("lan_ip") || "").trim(),
      });
      setPendingChange(change);
      setNotice("Draft saved. Validate, review, then apply it.");
      setError("");
    } catch (saveError) {
      setError(getErrorMessage(saveError, "Unable to stage PACS settings."));
    }
  }

  async function saveMachine(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authorization) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const values = {
      display_name: String(form.get("display_name") || "").trim(),
      modality: String(form.get("modality") || "").trim().toUpperCase(),
      remote_ae_title: String(form.get("remote_ae_title") || "").trim().toUpperCase(),
      ip_address: String(form.get("ip_address") || "").trim(),
      port: Number(form.get("port")),
      enabled: editingMachine?.enabled ?? true,
    };
    try {
      const change = await stageMachineChange(
        authorization,
        editingMachine ? "machine_update" : "machine_create",
        editingMachine ? { ...values, id: editingMachine.id } : values,
      );
      setPendingChange(change);
      setNotice(
        editingMachine
          ? "Machine edit draft saved. Validate, review, then apply it."
          : "Machine draft saved. Validate, review, then apply registration.",
      );
      setError("");
      formElement.reset();
      setEditingMachine(null);
    } catch (saveError) {
      setError(getErrorMessage(saveError, "Unable to stage machine registration."));
    }
  }

  async function stageMachineEnabled(machine: Machine) {
    if (!authorization) return;
    try {
      const change = await stageMachineChange(authorization, "machine_update", {
        id: machine.id,
        enabled: !machine.enabled,
      });
      setPendingChange(change);
      setNotice("Machine status draft saved. Validate, review, then apply it.");
    } catch (saveError) {
      setError(getErrorMessage(saveError, "Unable to stage machine status."));
    }
  }

  async function removeMachine(machine: Machine) {
    if (!authorization) return;
    const confirmed = window.confirm(
      `Permanently delete the registration for ${machine.display_name} (${machine.remote_ae_title})? This does not delete studies. Deletion will be blocked if the machine is enabled or has validated study associations.`,
    );
    if (!confirmed) return;
    await run(
      () => deleteMachine(authorization, machine.id),
      `${machine.display_name} registration deleted.`,
    );
  }

  async function validateFiles(selectedFiles: File[]) {
    if (!authorization || selectedFiles.length === 0) return;
    setFiles(selectedFiles);
    setImportSummary([]);
    setDuplicateDecisionRequired(false);
    setError("");
    setNotice("");
    try {
      setImportValidation(await validateDicomImport(authorization, selectedFiles));
    } catch (validationError) {
      setImportValidation(null);
      setError(getErrorMessage(validationError, "DICOM validation failed."));
    }
  }

  async function importSelected(policy?: "skip" | "overwrite") {
    if (!authorization || files.length === 0 || isImporting) return;
    const batchDuplicates = new Set(
      (importValidation?.files ?? [])
        .map((file, index) =>
          file.duplicates.some((duplicate) => duplicate.type === "BatchDuplicate")
            ? index
            : -1,
        )
        .filter((index) => index >= 0),
    );
    const progress = {
      total: files.length,
      completed: 0,
      succeeded: 0,
      skipped: 0,
      failed: 0,
      currentFile: "",
    };
    const results: string[] = [];
    setImportProgress(progress);
    setImportSummary([]);
    setIsImporting(true);
    setError("");
    setNotice("");
    try {
      for (const [index, file] of files.entries()) {
        setImportProgress({ ...progress, currentFile: file.name });
        if (batchDuplicates.has(index)) {
          progress.skipped += 1;
          progress.completed += 1;
          results.push(`${file.name}: skipped_duplicate (duplicate within selected batch)`);
        } else {
          try {
            const result = await importDicom(authorization, [file], policy);
            const item = result.summary[0];
            if (!item) throw new Error("The server returned no result for this file.");
            if (
              item.result === "imported"
              && (result.verification.failed || result.verification.verified_count !== 1)
            ) {
              throw new Error("Orthanc did not verify the imported instance.");
            }
            if (item.result === "imported") progress.succeeded += 1;
            else progress.skipped += 1;
            progress.completed += 1;
            results.push(`${file.name}: ${item.result}`);
          } catch (fileError) {
            progress.failed += 1;
            progress.completed += 1;
            results.push(`${file.name}: failed — ${getErrorMessage(fileError, "Import failed.")}`);
          }
        }
        setImportProgress({ ...progress, currentFile: "" });
        setImportSummary([...results]);
      }
      setNotice(
        `Batch complete: ${progress.succeeded} imported and verified, ${progress.skipped} skipped, ${progress.failed} failed.`,
      );
      setImportValidation(null);
      if (progress.failed > 0) {
        setError(`${progress.failed} file(s) failed. See the per-file results below.`);
      }
      await refresh();
    } finally {
      setIsImporting(false);
    }
  }

  async function exportActivity() {
    if (!authorization) return;
    try {
      await downloadActivity(authorization, activityCategory);
      setNotice("Filtered audit results downloaded as CSV.");
      setError("");
    } catch (exportError) {
      setError(getErrorMessage(exportError, "Unable to download audit activity."));
    }
  }

  async function checkMachine(machine: Machine) {
    if (!authorization) return;
    const result = await run(
      () =>
        checkMachineIdentity(
          authorization,
          machine.remote_ae_title,
          machine.ip_address,
        ),
      "Registration identity checked. Receiver-side ingestion is not gated by this API.",
    );
    if (result) {
      setNotice(
        result.registered
          ? `Registered and enabled: ${machine.remote_ae_title} at ${machine.ip_address}. Ingestion remains ${result.ingestion}.`
          : "Machine identity was rejected and logged.",
      );
    }
  }

  async function verifyStudies(machine: Machine, value: string) {
    if (!authorization) return;
    const ids = value.split(",").map((id) => id.trim()).filter(Boolean);
    const result = await run(
      () => verifyMachineStudies(authorization, machine.id, ids),
      "Orthanc-origin verification completed.",
    );
    if (result) {
      setNotice(
        `${result.associated_studies.length} study association(s) validated; ${result.rejected_studies.length} rejected.`,
      );
    }
  }

  async function filterMachineStudies(machine: Machine) {
    if (!authorization) return [];
    const result = await run(() => getMachineStudies(authorization, machine.id));
    return result?.results ?? [];
  }

  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Administration</h1>
          <p className="page-subtitle">Manage accounts, service status and approved PACS operations.</p>
        </div>
        <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <nav className="admin-tabs" aria-label="Administration sections">
        {sections.map((item) => (
          <button
            key={item}
            type="button"
            className={section === item ? "admin-tab active" : "admin-tab"}
            aria-current={section === item ? "page" : undefined}
            onClick={() => {
              setSection(item);
              setError("");
              setNotice("");
            }}
          >
            {item}
          </button>
        ))}
      </nav>

      {error && <p className="error-message" role="alert">{error}</p>}
      {notice && <p className="notice-message" role="status">{notice}</p>}
      {loading && <p className="loading-message" role="status">Loading administration data…</p>}

      {!loading && section === "System Overview" && overview && (
        <div className="admin-section">
          <div className="admin-metrics">
            <Metric label="Total studies" value={overview.total_studies ?? "Unavailable"} />
            <Metric label="Users" value={overview.users.total} />
            <Metric label="Staff / administrators" value={`${overview.users.staff} / ${overview.users.administrators}`} />
            <Metric label="Active viewing sessions" value={overview.active_viewing_sessions} />
          </div>
          <section className="detail-section">
            <h2>Service health summary</h2>
            <HealthList health={overview.service_health} />
          </section>
          <section className="detail-section">
            <h2>Recent activity</h2>
            <ActivityTable events={overview.recent_activity} />
          </section>
        </div>
      )}

      {!loading && section === "Users" && (
        <div className="admin-section">
          <section className="detail-section">
            <h2>Create user</h2>
            <form className="admin-form admin-user-form" onSubmit={(event) => void createAccount(event)}>
              <label className="field"><span>Username</span><input name="username" required maxLength={150} /></label>
              <label className="field"><span>Email</span><input name="email" type="email" /></label>
              <label className="field"><span>Account type</span>
                <select name="account_type" defaultValue="staff">
                  <option value="staff">Staff</option>
                  <option value="administrator">Administrator</option>
                </select>
              </label>
              <label className="field"><span>Initial password</span><input name="password" type="password" required autoComplete="new-password" /></label>
              <button className="button button-primary" type="submit">Create user</button>
            </form>
          </section>
          <section className="detail-section">
            <h2>Accounts <span className="result-count">{users.length} users</span></h2>
            <div className="table-scroll">
              <table className="study-table">
                <thead><tr><th>Username</th><th>Email</th><th>Type</th><th>Status</th><th>Last login</th><th>Actions</th></tr></thead>
                <tbody>{users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.username}</td><td>{user.email || "—"}</td><td>{user.account_type}</td>
                    <td>{user.is_active ? "Active" : "Inactive"}</td>
                    <td>{user.last_login ? formatDate(user.last_login) : "Never"}</td>
                    <td className="admin-actions">
                      <button className="button button-small button-secondary" type="button" onClick={() => void changeUser(user)}>{user.is_active ? "Deactivate" : "Activate"}</button>
                      <button className="button button-small button-secondary" type="button" onClick={() => void resetPassword(user)}>Reset password</button>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {!loading && section === "Activity" && activity && (
        <section className="detail-section admin-section">
          <div className="admin-actions audit-controls">
            <h2>Audit &amp; activity</h2>
            <label className="field">
              <span>Action category</span>
              <select
                value={activityCategory}
                onChange={(event) => setActivityCategory(event.target.value as ActivityCategory)}
              >
                <option value="all">All actions</option>
                <option value="login">Login events</option>
                <option value="viewing">Viewing events</option>
                <option value="export">Export events</option>
              </select>
            </label>
            <button className="button button-secondary" type="button" onClick={() => void exportActivity()}>
              Download filtered CSV
            </button>
          </div>
          {activity.audit_gaps.map((gap) => <p className="notice-message" key={gap}>{gap}</p>)}
          <ActivityTable events={activity.results} />
        </section>
      )}

      {!loading && section === "Service Health" && health && (
        <section className="detail-section admin-section">
          <h2>Service health: <StatusText status={health.overall} /></h2>
          <p className="result-count">Checked {formatDate(health.checked_at)}</p>
          <HealthList health={health} />
        </section>
      )}

      {!loading && section === "Machine Management" && (
        <div className="admin-section">
          <section className="detail-section">
            <h2>Register machine</h2>
            <p className="page-subtitle">Registration changes follow Edit → Validate → Review → Apply.</p>
            <form key={editingMachine?.id ?? "new-machine"} className="admin-form admin-machine-form" onSubmit={(event) => void saveMachine(event)}>
              <label className="field"><span>Display name</span><input name="display_name" required maxLength={120} defaultValue={editingMachine?.display_name} /></label>
              <label className="field"><span>Modality</span><input name="modality" required maxLength={16} placeholder="CT, MR, CR…" defaultValue={editingMachine?.modality} /></label>
              <label className="field"><span>Remote AE Title</span><input name="remote_ae_title" required maxLength={16} defaultValue={editingMachine?.remote_ae_title} /></label>
              <label className="field"><span>IP Address</span><input name="ip_address" required defaultValue={editingMachine?.ip_address} /></label>
              <label className="field"><span>Port</span><input name="port" type="number" min={1} max={65535} required defaultValue={editingMachine?.port} /></label>
              <div className="admin-actions">
                <button className="button button-primary" type="submit">{editingMachine ? "Stage machine edit" : "Stage registration"}</button>
                {editingMachine && <button className="button button-secondary" type="button" onClick={() => setEditingMachine(null)}>Cancel edit</button>}
              </div>
            </form>
          </section>
          {pendingChange && (
            <ChangeWorkflow
              change={pendingChange}
              onAdvance={() => void advanceChange(pendingChange)}
              onCancel={() => void cancelStagedChange(pendingChange)}
            />
          )}
          <section className="detail-section">
            <h2>Registered machines</h2>
            <div className="table-scroll">
              <table className="study-table">
                <thead><tr><th>Machine</th><th>Modality</th><th>Remote identity</th><th>Registration</th><th>Connectivity</th><th>Ingestion</th><th>Actions</th></tr></thead>
                <tbody>{machines.map((machine) => (
                  <MachineRow
                    key={machine.id}
                    machine={machine}
                    onConnectivity={() => void testConnectivity(machine)}
                    onIdentity={() => void checkMachine(machine)}
                    onEnabled={() => void stageMachineEnabled(machine)}
                    onVerify={(ids) => void verifyStudies(machine, ids)}
                    onFilter={() => filterMachineStudies(machine)}
                    onEdit={() => setEditingMachine(machine)}
                    onDelete={() => void removeMachine(machine)}
                  />
                ))}</tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {!loading && section === "DICOM Import" && (
        <section className="detail-section admin-section">
          <h2>Historical DICOM import</h2>
          <p className="page-subtitle">Select individual DICOM files or a folder. ZIP files are not accepted.</p>
          <div className="admin-import-controls">
            <label className="field">
              <span>Individual DICOM files</span>
              <input type="file" multiple disabled={isImporting} onChange={(event) => void validateFiles(Array.from(event.target.files || []))} />
            </label>
            <label className="field">
              <span>DICOM folder</span>
              <input
                type="file"
                multiple
                disabled={isImporting}
                ref={(input) => input?.setAttribute("webkitdirectory", "")}
                onChange={(event) => void validateFiles(Array.from(event.target.files || []))}
              />
            </label>
          </div>
          {files.length > 0 && <p className="result-count">{files.length} selected file(s)</p>}
          {importProgress && (
            <div className="import-validation" aria-live="polite">
              <h3>Import queue progress</h3>
              <p>
                {isImporting ? `Processing ${importProgress.currentFile}` : "Batch processing finished"}
                {" — "}completed {importProgress.completed} of {importProgress.total},
                {" "}{importProgress.total - importProgress.completed} remaining;
                {" "}{importProgress.succeeded} imported and verified,
                {" "}{importProgress.skipped} skipped,
                {" "}{importProgress.failed} failed.
              </p>
            </div>
          )}
          {importValidation && (
            <div className="import-validation">
              <h3>Validation summary</h3>
              <ul>{importValidation.files.map((file) => (
                <li key={file.filename}>
                  {file.filename}: {file.valid ? "Valid DICOM" : "Invalid"}
                  {file.duplicates.length > 0 && ` — ${file.duplicates.length} duplicate instance(s)`}
                </li>
              ))}</ul>
              {importValidation.duplicate_count > 0 || duplicateDecisionRequired ? (
                <div className="search-actions">
                  <button className="button button-primary" type="button" disabled={isImporting} onClick={() => void importSelected("skip")}>Skip duplicates</button>
                  <button className="button button-secondary" type="button" disabled={isImporting} onClick={() => void importSelected("overwrite")}>Overwrite duplicates</button>
                </div>
              ) : (
                <button className="button button-primary" type="button" disabled={isImporting} onClick={() => void importSelected()}>Import files</button>
              )}
            </div>
          )}
          {importSummary.length > 0 && (
            <div className="import-validation">
              <h3>Import summary &amp; verification</h3>
              <ul>{importSummary.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
        </section>
      )}

      {!loading && section === "Network Configuration" && network && (
        <div className="admin-section">
          <section className="detail-section">
            <h2>Approved PACS settings</h2>
            <p className="page-subtitle">Secrets and raw Orthanc files are not exposed. Changes are staged and never trigger an automatic restart.</p>
            <form className="admin-form admin-network-form" onSubmit={(event) => void saveNetwork(event)}>
              <label className="field"><span>AE Title</span><input name="ae_title" maxLength={16} defaultValue={network.ae_title} required /></label>
              <label className="field"><span>DICOM Port</span><input name="dicom_port" type="number" min={1} max={65535} defaultValue={network.dicom_port} required /></label>
              <label className="field"><span>LAN IP</span><input name="lan_ip" defaultValue={network.lan_ip} /></label>
              <button className="button button-primary" type="submit">Save as draft</button>
            </form>
            <p className="result-count">Last applied: {formatDate(network.updated_at)}</p>
          </section>
          {pendingChange && (
            <ChangeWorkflow
              change={pendingChange}
              onAdvance={() => void advanceChange(pendingChange)}
              onCancel={() => void cancelStagedChange(pendingChange)}
            />
          )}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <article className="admin-metric"><p>{label}</p><strong>{value}</strong></article>;
}

function HealthList({ health }: { health: ServiceHealth }) {
  return <ul className="health-list">{health.services.map((service) => (
    <li key={service.name}>
      <span>{service.name}</span><StatusText status={service.status} /><p>{service.message}</p>
    </li>
  ))}</ul>;
}

function StatusText({ status }: { status: string }) {
  return <strong className={`health-status status-${status}`}>{status}</strong>;
}

function ActivityTable({ events }: { events: ActivityEvent[] }) {
  if (events.length === 0) return <p className="empty-state">No recorded activity is available.</p>;
  return (
    <div className="table-scroll">
      <table className="study-table">
        <thead><tr><th>Time</th><th>Activity</th><th>User</th><th>Outcome</th><th>Source</th></tr></thead>
        <tbody>{events.map((event) => (
          <tr key={event.id}>
            <td>{formatDate(event.created_at)}</td>
            <td>{event.label}{event.details.action ? ` — ${event.details.action}` : ""}</td>
            <td>{event.username || "System"}</td><td>{event.outcome}</td><td>{event.source_ip || "—"}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function MachineRow({
  machine,
  onConnectivity,
  onIdentity,
  onEnabled,
  onVerify,
  onFilter,
  onEdit,
  onDelete,
}: {
  machine: Machine;
  onConnectivity: () => void;
  onIdentity: () => void;
  onEnabled: () => void;
  onVerify: (ids: string) => void;
  onFilter: () => Promise<{ study_id: string; validated_at: string }[]>;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [studyIds, setStudyIds] = useState("");
  const [associatedStudies, setAssociatedStudies] = useState<string[] | null>(null);
  return (
    <tr>
      <td>{machine.display_name}<br /><span className="result-count">{machine.ip_address}:{machine.port}</span></td>
      <td>{machine.modality}</td><td>{machine.remote_ae_title}</td>
      <td>{machine.registration}</td><td>{machine.connectivity}</td><td>{machine.ingestion}</td>
      <td>
        <div className="admin-actions">
          <button className="button button-small button-secondary" type="button" onClick={onConnectivity}>Test connectivity</button>
          <button className="button button-small button-secondary" type="button" onClick={onIdentity}>Check identity</button>
          <button className="button button-small button-secondary" type="button" onClick={onEnabled}>{machine.enabled ? "Stage disable" : "Stage enable"}</button>
          <button className="button button-small button-secondary" type="button" onClick={onEdit}>Edit details</button>
          <button className="button button-small button-danger" type="button" onClick={onDelete}>Delete registration</button>
          <label className="field">
            <span>Study IDs to verify (comma-separated)</span>
            <input value={studyIds} onChange={(event) => setStudyIds(event.target.value)} />
          </label>
          <button className="button button-small button-secondary" type="button" disabled={!studyIds.trim()} onClick={() => onVerify(studyIds)}>Verify origins</button>
          <button className="button button-small button-secondary" type="button" onClick={async () => setAssociatedStudies((await onFilter()).map((study) => study.study_id))}>Filter associated studies</button>
          {associatedStudies && <span className="machine-study-results">{associatedStudies.length ? associatedStudies.join(", ") : "No validated studies"}</span>}
        </div>
      </td>
    </tr>
  );
}

function ChangeWorkflow({
  change,
  onAdvance,
  onCancel,
}: {
  change: ConfigurationChange;
  onAdvance: () => void;
  onCancel: () => void;
}) {
  const nextAction = change.state === "edit"
    ? "Validate"
    : change.state === "validated"
      ? "Review"
      : change.state === "reviewed"
        ? "Apply"
        : "Applied";
  return (
    <section className="detail-section change-workflow">
      <h2>Configuration staging</h2>
      <p>{change.change_type.replace("_", " ")} — {change.state}</p>
      <pre>{JSON.stringify(change.proposed_values, null, 2)}</pre>
      {change.validation_errors.map((item) => <p className="error-message" key={item}>{item}</p>)}
      {change.state !== "applied" && change.state !== "cancelled" && (
        <div className="admin-actions">
          <button className="button button-primary" type="button" onClick={onAdvance}>{nextAction}</button>
          <button className="button button-secondary" type="button" onClick={onCancel}>Cancel draft</button>
        </div>
      )}
      {change.restart_required && <p className="notice-message">Manual restart required after apply. No automatic restart will occur.</p>}
    </section>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
