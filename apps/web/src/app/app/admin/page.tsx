"use client";

import { useState } from "react";
import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LoadingRows, PageHeader, StatusChip } from "@/components/app/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/field";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, qs } from "@/lib/api";
import { LEVELS, title, when } from "@/lib/app/format";
import { useApi } from "@/lib/app/use-api";

type User = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  status: string;
  last_login_at: string | null;
};
type Key = {
  id: string;
  name: string;
  prefix?: string;
  scopes: string[];
  created_at: string;
  last_used_at?: string | null;
  expires_at?: string | null;
  revoked_at?: string | null;
};
type Hook = {
  id: string;
  name: string;
  url: string;
  min_level: string;
  include_coordinates: boolean;
  status?: string;
  enabled?: boolean;
  created_at: string;
};
type Audit = {
  id: number;
  actor_id: string | null;
  actor_type: string;
  action: string;
  object_type: string | null;
  object_id: string | null;
  ip: string | null;
  at: string;
};
type Risk = {
  min_level: string;
  include_coordinates: boolean;
  retention_days: number;
  model_training_opt_in: boolean;
  daily_briefing: boolean;
  weekly_briefing: boolean;
  briefing_email: boolean;
};

const ROLES = ["viewer", "analyst", "manager", "tenant_admin"];

/** Shown once: the secret is never retrievable afterwards. */
function Secret({ value, onClose, label }: { value: string | null; onClose: () => void; label: string }) {
  return (
    <Dialog open={!!value} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle className="text-h4 text-ink">{label}</DialogTitle>
        <DialogDescription className="text-small text-slate-600">
          Copy it now. For your security it is shown only once.
        </DialogDescription>
        <code className="mt-4 block break-all rounded-control border border-line bg-slate-50 p-3 font-mono text-small text-ink">
          {value}
        </code>
        <div className="mt-4 flex gap-2">
          <Button onClick={() => void navigator.clipboard?.writeText(value ?? "")}>Copy</Button>
          <Button variant="secondary" onClick={onClose}>
            I have saved it
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Users() {
  const res = useApi<{ items: User[] }>("/admin/users");
  const toast = useToast();
  const [open, setOpen] = useState(false);
  async function invite(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    try {
      await api("/admin/users", {
        method: "POST",
        body: { email: d.get("email"), display_name: d.get("name"), role: d.get("role") },
      });
      toast("Invitation sent.");
      setOpen(false);
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The invitation could not be sent.", "error");
    }
  }
  async function patch(u: User, body: Record<string, string>, confirm?: string) {
    if (confirm && !window.confirm(confirm)) return;
    try {
      await api(`/admin/users/${u.id}`, { method: "PATCH", body });
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The change could not be saved.", "error");
    }
  }
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  return (
    <div>
      <div className="mb-3 flex justify-end">
        <Button size="sm" onClick={() => setOpen(true)}>
          Invite user
        </Button>
      </div>
      {!res.data ? (
        <LoadingRows rows={4} />
      ) : (
        <DataTable
          rows={res.data.items}
          rowKey={(u) => u.id}
          caption="Users"
          exportName="users"
          columns={[
            { key: "n", header: "Name", cell: (u) => u.display_name, value: (u) => u.display_name },
            { key: "e", header: "Email", cell: (u) => u.email, value: (u) => u.email },
            {
              key: "r",
              header: "Role",
              cell: (u) => (
                <Select
                  aria-label={`Role of ${u.email}`}
                  className="h-8 w-40 text-small"
                  value={u.role}
                  onChange={(e) =>
                    void patch(
                      u,
                      { role: e.target.value },
                      `Change the role of ${u.email} to ${title(e.target.value)}?`,
                    )
                  }
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {title(r)}
                    </option>
                  ))}
                </Select>
              ),
            },
            {
              key: "s",
              header: "Status",
              cell: (u) => <StatusChip status={u.status} />,
              value: (u) => u.status,
            },
            {
              key: "l",
              header: "Last sign-in",
              cell: (u) => (u.last_login_at ? when(u.last_login_at) : "never"),
              value: (u) => u.last_login_at,
            },
            {
              key: "a",
              header: "",
              cell: (u) => (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    void patch(
                      u,
                      { status: u.status === "active" ? "disabled" : "active" },
                      u.status === "active" ? `Disable ${u.email}? They will be signed out.` : undefined,
                    )
                  }
                >
                  {u.status === "active" ? "Disable" : "Enable"}
                </Button>
              ),
            },
          ]}
        />
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">Invite a user</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            They receive an email to choose a password. Administrators must set up two-factor authentication.
          </DialogDescription>
          <form onSubmit={invite} className="mt-4 space-y-3">
            <Field label="Name" htmlFor="u-name">
              <Input id="u-name" name="name" required />
            </Field>
            <Field label="Email" htmlFor="u-email">
              <Input id="u-email" name="email" type="email" required />
            </Field>
            <Field label="Role" htmlFor="u-role">
              <Select id="u-role" name="role" defaultValue="analyst">
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {title(r)}
                  </option>
                ))}
              </Select>
            </Field>
            <Button type="submit">Send invitation</Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Keys() {
  const res = useApi<{ items: Key[] }>("/admin/api-keys");
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    try {
      const r = await api<{ secret?: string; key?: string }>("/admin/api-keys", {
        method: "POST",
        body: {
          name: d.get("name"),
          scopes: d.getAll("scopes"),
          expires_in_days: d.get("days") ? Number(d.get("days")) : null,
        },
      });
      setOpen(false);
      setSecret(r.secret ?? r.key ?? null);
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The key could not be created.", "error");
    }
  }
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  return (
    <div>
      <div className="mb-3 flex justify-end">
        <Button size="sm" onClick={() => setOpen(true)}>
          Create API key
        </Button>
      </div>
      {!res.data ? (
        <LoadingRows rows={3} />
      ) : (
        <DataTable
          rows={res.data.items}
          rowKey={(k) => k.id}
          caption="API keys"
          exportName="api-keys"
          empty={{
            title: "No API keys",
            body: "Create a key to call the API from your own systems. Keys are scoped and can be revoked at any time.",
          }}
          columns={[
            { key: "n", header: "Name", cell: (k) => k.name, value: (k) => k.name },
            { key: "s", header: "Scopes", cell: (k) => k.scopes.join(", ") },
            { key: "c", header: "Created", cell: (k) => when(k.created_at), value: (k) => k.created_at },
            { key: "u", header: "Last used", cell: (k) => (k.last_used_at ? when(k.last_used_at) : "never") },
            {
              key: "st",
              header: "Status",
              cell: (k) => <StatusChip status={k.revoked_at ? "dismissed" : "active"} />,
            },
            {
              key: "a",
              header: "",
              cell: (k) =>
                k.revoked_at ? null : (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      if (!window.confirm(`Revoke the key "${k.name}"? Systems using it will stop working.`))
                        return;
                      await api(`/admin/api-keys/${k.id}`, { method: "DELETE" }).then(res.reload, () =>
                        toast("The key could not be revoked.", "error"),
                      );
                    }}
                  >
                    Revoke
                  </Button>
                ),
            },
          ]}
        />
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">Create an API key</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Give a key only the access it needs.
          </DialogDescription>
          <form onSubmit={create} className="mt-4 space-y-3">
            <Field label="Name" htmlFor="k-name">
              <Input id="k-name" name="name" required maxLength={80} />
            </Field>
            <fieldset>
              <legend className="mb-1 text-small font-medium text-ink">Scopes</legend>
              <div className="flex flex-wrap gap-3 text-small">
                {["read", "alerts", "assets:write", "reports"].map((s) => (
                  <label key={s} className="flex items-center gap-1.5">
                    <Checkbox name="scopes" value={s} defaultChecked={s === "read"} />
                    {s}
                  </label>
                ))}
              </div>
            </fieldset>
            <Field label="Expires after (days, optional)" htmlFor="k-days">
              <Input id="k-days" name="days" type="number" min={1} max={730} />
            </Field>
            <Button type="submit">Create key</Button>
          </form>
        </DialogContent>
      </Dialog>
      <Secret value={secret} onClose={() => setSecret(null)} label="Your new API key" />
    </div>
  );
}

function Hooks() {
  const res = useApi<{ items: Hook[] }>("/admin/webhooks");
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [log, setLog] = useState<Hook | null>(null);
  const deliveries = useApi<{
    items: {
      id: string;
      status: string;
      response_code?: number | null;
      attempts?: number;
      created_at: string;
      event?: string;
    }[];
  }>(log ? `/admin/webhooks/${log.id}/deliveries?limit=30` : null);
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    try {
      const r = await api<{ secret?: string; signing_secret?: string }>("/admin/webhooks", {
        method: "POST",
        body: {
          name: d.get("name"),
          url: d.get("url"),
          min_level: d.get("min_level"),
          include_coordinates: d.get("coords") === "on",
        },
      });
      setOpen(false);
      setSecret(r.secret ?? r.signing_secret ?? null);
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The webhook could not be created.", "error");
    }
  }
  const act = async (h: Hook, path: string, ok: string, confirm?: string) => {
    if (confirm && !window.confirm(confirm)) return;
    try {
      const r = await api<{ secret?: string; signing_secret?: string }>(`/admin/webhooks/${h.id}${path}`, {
        method: path === "" ? "DELETE" : "POST",
      });
      const s = r?.secret ?? r?.signing_secret;
      if (s) setSecret(s);
      else toast(ok);
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That did not work.", "error");
    }
  };
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  return (
    <div>
      <div className="mb-3 flex justify-end">
        <Button size="sm" onClick={() => setOpen(true)}>
          Add webhook
        </Button>
      </div>
      {!res.data ? (
        <LoadingRows rows={3} />
      ) : (
        <DataTable
          rows={res.data.items}
          rowKey={(h) => h.id}
          caption="Webhooks"
          empty={{
            title: "No webhooks",
            body: "Add a webhook to receive signed alert notifications at your own HTTPS endpoint.",
          }}
          columns={[
            { key: "n", header: "Name", cell: (h) => h.name },
            {
              key: "u",
              header: "URL",
              cell: (h) => <span className="break-all font-mono text-caption">{h.url}</span>,
            },
            { key: "l", header: "Minimum level", cell: (h) => h.min_level },
            {
              key: "c",
              header: "Coordinates",
              cell: (h) => (h.include_coordinates ? "Included" : "Omitted"),
            },
            {
              key: "a",
              header: "Actions",
              cell: (h) => (
                <span className="flex flex-wrap gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void act(h, "/test", "A test delivery was queued.")}
                  >
                    Test
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setLog(h)}>
                    Deliveries
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      void act(
                        h,
                        "/rotate-secret",
                        "",
                        "Rotate the signing secret? The old one stays valid for seven days.",
                      )
                    }
                  >
                    Rotate secret
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void act(h, "", "Webhook deleted.", `Delete the webhook "${h.name}"?`)}
                  >
                    Delete
                  </Button>
                </span>
              ),
            },
          ]}
        />
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle className="text-h4 text-ink">Add a webhook</DialogTitle>
          <DialogDescription className="text-small text-slate-600">
            Deliveries are signed. HTTPS addresses on the public internet only.
          </DialogDescription>
          <form onSubmit={create} className="mt-4 space-y-3">
            <Field label="Name" htmlFor="w-name">
              <Input id="w-name" name="name" required />
            </Field>
            <Field label="URL" htmlFor="w-url">
              <Input id="w-url" name="url" type="url" required placeholder="https://" />
            </Field>
            <Field label="Minimum level" htmlFor="w-level">
              <Select id="w-level" name="min_level" defaultValue="high">
                {LEVELS.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </Select>
            </Field>
            <label className="flex items-center gap-2 text-small">
              <Checkbox name="coords" /> Include asset coordinates in payloads
            </label>
            <Button type="submit">Add webhook</Button>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={!!log} onOpenChange={(o) => !o && setLog(null)}>
        <DialogContent className="max-w-2xl">
          <DialogTitle className="text-h4 text-ink">Deliveries: {log?.name}</DialogTitle>
          <DialogDescription className="text-small text-slate-600">The last 30 attempts.</DialogDescription>
          <div className="mt-3">
            {!deliveries.data ? (
              <LoadingRows rows={3} />
            ) : (
              <DataTable
                rows={deliveries.data.items}
                rowKey={(d) => d.id}
                caption="Webhook deliveries"
                empty={{ title: "No deliveries yet", body: "Send a test delivery to see it here." }}
                columns={[
                  { key: "t", header: "Time", cell: (d) => when(d.created_at) },
                  { key: "s", header: "Status", cell: (d) => d.status },
                  { key: "c", header: "HTTP", cell: (d) => d.response_code ?? "n/a" },
                  { key: "a", header: "Attempts", cell: (d) => d.attempts ?? 1 },
                ]}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
      <Secret value={secret} onClose={() => setSecret(null)} label="Webhook signing secret" />
    </div>
  );
}

function AuditLog() {
  const [action, setAction] = useState("");
  const res = useApi<{ items: Audit[] }>(`/admin/audit${qs({ action, limit: 100 })}`);
  const verify = useApi<{ intact: boolean; entries_checked: number }>("/admin/audit/verify");
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  const ok = verify.data?.intact;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <label htmlFor="au-a" className="mb-1 block text-caption text-slate-600">
            Action contains
          </label>
          <Input
            id="au-a"
            className="h-9 w-56"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="e.g. auth.login"
          />
        </div>
        <p className="text-small text-slate-600">
          Integrity:{" "}
          {ok === undefined ? (
            "checking"
          ) : ok ? (
            <Badge tone="success">Hash chain verified, {verify.data?.entries_checked} entries</Badge>
          ) : (
            <Badge tone="danger">Chain broken</Badge>
          )}
        </p>
      </div>
      {!res.data ? (
        <LoadingRows rows={6} />
      ) : (
        <DataTable
          rows={res.data.items}
          rowKey={(a) => String(a.id)}
          caption="Audit log"
          exportName="audit-log"
          columns={[
            { key: "t", header: "Time", cell: (a) => when(a.at), value: (a) => a.at },
            { key: "a", header: "Action", cell: (a) => a.action, value: (a) => a.action },
            {
              key: "o",
              header: "Object",
              cell: (a) => (a.object_type ? `${a.object_type} ${a.object_id?.slice(0, 8) ?? ""}` : ""),
              value: (a) => a.object_type,
            },
            {
              key: "w",
              header: "Actor",
              cell: (a) => `${a.actor_type} ${a.actor_id?.slice(0, 8) ?? ""}`,
              value: (a) => a.actor_id,
            },
            { key: "i", header: "Address", cell: (a) => (a.ip ?? "").replace("/32", ""), value: (a) => a.ip },
          ]}
        />
      )}
    </div>
  );
}

function Config() {
  const res = useApi<Risk>("/admin/risk-config");
  const toast = useToast();
  const [saved, setSaved] = useState<{ at: string; cfg: Risk }[]>([]);
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const body: Risk = {
      min_level: String(d.get("min_level")),
      include_coordinates: d.get("coords") === "on",
      retention_days: Number(d.get("days")),
      model_training_opt_in: d.get("train") === "on",
      daily_briefing: d.get("daily") === "on",
      weekly_briefing: d.get("weekly") === "on",
      briefing_email: d.get("email") === "on",
    };
    try {
      if (res.data)
        setSaved((s) => [{ at: new Date().toISOString(), cfg: res.data as Risk }, ...s].slice(0, 5));
      await api("/admin/risk-config", { method: "PUT", body });
      toast("Settings saved.");
      res.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "The settings could not be saved.", "error");
    }
  }
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  if (!res.data) return <LoadingRows rows={4} />;
  const r = res.data;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <h2 className="text-h4 text-ink">Risk and privacy</h2>
        <form key={JSON.stringify(r)} onSubmit={save} className="mt-3 space-y-3">
          <Field label="Default minimum alert level" htmlFor="rc-level">
            <Select id="rc-level" name="min_level" defaultValue={r.min_level}>
              {LEVELS.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </Select>
          </Field>
          <Field label="Keep alert history for (days)" htmlFor="rc-days">
            <Input
              id="rc-days"
              name="days"
              type="number"
              min={30}
              max={3650}
              defaultValue={r.retention_days}
            />
          </Field>
          <label className="flex items-center gap-2 text-small">
            <Checkbox name="coords" defaultChecked={r.include_coordinates} /> Include asset coordinates in
            emails and webhooks
          </label>
          <label className="flex items-center gap-2 text-small">
            <Checkbox name="train" defaultChecked={r.model_training_opt_in} /> Allow my confirmed location
            corrections to improve models
          </label>
          <label className="flex items-center gap-2 text-small">
            <Checkbox name="daily" defaultChecked={r.daily_briefing} /> Create a daily briefing
          </label>
          <label className="flex items-center gap-2 text-small">
            <Checkbox name="weekly" defaultChecked={r.weekly_briefing} /> Create a weekly briefing
          </label>
          <label className="flex items-center gap-2 text-small">
            <Checkbox name="email" defaultChecked={r.briefing_email} /> Email briefings to users
          </label>
          <Button type="submit">Save</Button>
        </form>
      </Card>
      <Card>
        <h2 className="text-h4 text-ink">Security settings</h2>
        <dl className="mt-3 space-y-2 text-small">
          <div>
            <dt className="text-slate-600">Two-factor authentication</dt>
            <dd className="text-ink">
              Required for tenant administrators and platform administrators; optional for other roles.
            </dd>
          </div>
          <div>
            <dt className="text-slate-600">Session length</dt>
            <dd className="text-ink">
              Access tokens last 15 minutes and refresh automatically; a session ends after 7 days or 30
              minutes of inactivity.
            </dd>
          </div>
          <div>
            <dt className="text-slate-600">Audit log</dt>
            <dd className="text-ink">Append-only and hash chained. See the Audit log tab.</dd>
          </div>
        </dl>
        <p className="mt-3 text-caption text-slate-600">
          These policies are fixed by the platform in this release and cannot be changed per organisation.
        </p>
        <h3 className="mt-5 text-small font-medium text-ink">Version history (this session)</h3>
        {saved.length === 0 ? (
          <p className="text-caption text-slate-600">
            Changes made now are listed here. The audit log keeps the permanent record.
          </p>
        ) : (
          <ul className="mt-1 space-y-1 text-caption text-slate-600">
            {saved.map((s, i) => (
              <li key={i}>
                {when(s.at)}: previously level {s.cfg.min_level}, retention {s.cfg.retention_days} days
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function Admin() {
  return (
    <>
      <PageHeader
        title="Administration"
        description="People, access, integrations, audit and organisation settings."
      />
      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">Users and roles</TabsTrigger>
          <TabsTrigger value="keys">API keys</TabsTrigger>
          <TabsTrigger value="hooks">Webhooks</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
          <TabsTrigger value="config">Risk and security</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="mt-4">
          <Users />
        </TabsContent>
        <TabsContent value="keys" className="mt-4">
          <Keys />
        </TabsContent>
        <TabsContent value="hooks" className="mt-4">
          <Hooks />
        </TabsContent>
        <TabsContent value="audit" className="mt-4">
          <AuditLog />
        </TabsContent>
        <TabsContent value="config" className="mt-4">
          <Config />
        </TabsContent>
      </Tabs>
      <div className="mt-6">
        <Disclaimer />
      </div>
    </>
  );
}
