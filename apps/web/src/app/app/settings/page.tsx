"use client";

import { useState } from "react";
import { DataTable } from "@/components/app/data-table";
import { Disclaimer, ErrorState, LoadingRows, PageHeader } from "@/components/app/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox, Field, Input } from "@/components/ui/field";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { when } from "@/lib/app/format";
import { useSession } from "@/lib/app/session";
import { useApi } from "@/lib/app/use-api";

type Sess = {
  id: string;
  started_at: string;
  last_active_at: string;
  user_agent: string;
  ip: string;
  expires_at: string;
  current: boolean;
};

function Mfa() {
  const { me, reload } = useSession();
  const toast = useToast();
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  async function start() {
    try {
      setSetup(await api("/auth/mfa/setup", { method: "POST", body: {} }));
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Setup could not start.", "error");
    }
  }
  async function verify(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api<{ recovery_codes?: string[] }>("/auth/mfa/verify", {
        method: "POST",
        body: { code: String(new FormData(e.currentTarget).get("code")).replace(/\s/g, "") },
      });
      setCodes(r.recovery_codes ?? []);
      setSetup(null);
      await reload();
      toast("Two-factor authentication is on.");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That code was not accepted.", "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <h2 className="text-h4 text-ink">Two-factor authentication</h2>
      <p className="mt-1 text-small text-slate-600">
        Status: {me.mfa_enabled ? <Badge tone="success">On</Badge> : <Badge tone="warning">Off</Badge>}.
        Administrators must use it. Use an authenticator app such as any TOTP app.
      </p>
      {codes.length ? (
        <div className="mt-4 rounded-control border border-warning/50 p-3">
          <p className="text-small font-medium text-ink">
            Save these recovery codes now. Each works once and they are not shown again.
          </p>
          <ul className="mt-2 grid grid-cols-2 gap-1 font-mono text-small">
            {codes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <Button size="sm" variant="secondary" className="mt-3" onClick={() => setCodes([])}>
            I saved them
          </Button>
        </div>
      ) : null}
      {!me.mfa_enabled && !setup ? (
        <Button className="mt-4" onClick={() => void start()}>
          Set up an authenticator
        </Button>
      ) : null}
      {setup ? (
        <form method="post" onSubmit={verify} className="mt-4 space-y-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt="QR code for your authenticator app"
            width={176}
            height={176}
            className="rounded-control border border-line bg-white p-2"
            src={`data:image/svg+xml;utf8,${encodeURIComponent(setup.qr_svg)}`}
          />
          <p className="text-caption text-slate-600">
            Cannot scan? Enter this key: <span className="font-mono text-ink">{setup.secret}</span>
          </p>
          <Field label="6 digit code" htmlFor="mfa-code">
            <Input
              id="mfa-code"
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              className="w-40"
            />
          </Field>
          <Button type="submit" disabled={busy}>
            Turn on
          </Button>
        </form>
      ) : null}
    </Card>
  );
}

export default function Settings() {
  const { me, reload } = useSession();
  const toast = useToast();
  const sessions = useApi<{ items: Sess[] }>("/auth/sessions");
  const [email, setEmail] = useState(me.notifications?.email ?? true);
  async function saveNotifications(next: boolean) {
    setEmail(next);
    try {
      await api("/auth/me/notifications", { method: "PATCH", body: { email: next } });
      await reload();
      toast("Notification preference saved.");
    } catch {
      setEmail(!next);
      toast("The preference could not be saved.", "error");
    }
  }
  return (
    <>
      <PageHeader title="Settings" description="Your profile, sign-in security and notifications." />
      <Tabs defaultValue="profile">
        <TabsList>
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
          <TabsTrigger value="sessions">Sessions</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
        </TabsList>
        <TabsContent value="profile" className="mt-4">
          <Card className="max-w-lg">
            <dl className="grid grid-cols-[8rem_1fr] gap-2 text-small">
              <dt className="text-slate-600">Name</dt>
              <dd className="text-ink">{me.display_name}</dd>
              <dt className="text-slate-600">Email</dt>
              <dd className="text-ink">{me.email}</dd>
              <dt className="text-slate-600">Role</dt>
              <dd className="text-ink">{me.role.replace(/_/g, " ")}</dd>
            </dl>
            <p className="mt-3 text-caption text-slate-600">
              Name, email and role are managed by your organisation administrator.
            </p>
          </Card>
        </TabsContent>
        <TabsContent value="security" className="mt-4 max-w-2xl">
          <Mfa />
        </TabsContent>
        <TabsContent value="sessions" className="mt-4">
          {sessions.error ? (
            <ErrorState error={sessions.error} onRetry={sessions.reload} />
          ) : !sessions.data ? (
            <LoadingRows rows={3} />
          ) : (
            <DataTable
              rows={sessions.data.items}
              rowKey={(s) => s.id}
              caption="Active sessions"
              columns={[
                {
                  key: "d",
                  header: "Device",
                  cell: (s) => (
                    <span>
                      {s.user_agent.slice(0, 60)}{" "}
                      {s.current ? <Badge tone="success">This session</Badge> : null}
                    </span>
                  ),
                },
                { key: "ip", header: "Address", cell: (s) => s.ip.replace("/32", "") },
                { key: "a", header: "Last active", cell: (s) => when(s.last_active_at) },
                {
                  key: "x",
                  header: "",
                  cell: (s) =>
                    s.current ? null : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          if (!window.confirm("Sign out this session?")) return;
                          await api(`/auth/sessions/${s.id}`, { method: "DELETE" }).then(
                            sessions.reload,
                            () => toast("The session could not be ended.", "error"),
                          );
                        }}
                      >
                        Sign out
                      </Button>
                    ),
                },
              ]}
            />
          )}
        </TabsContent>
        <TabsContent value="notifications" className="mt-4">
          <Card className="max-w-lg">
            <label className="flex items-start gap-3 text-small">
              <Checkbox checked={email} onChange={(e) => void saveNotifications(e.target.checked)} />{" "}
              <span>
                <span className="font-medium text-ink">Email me about high and critical alerts</span>
                <br />
                <span className="text-slate-600">
                  At most 10 emails per hour. Live alerts also appear in the bell at the top of every page.
                </span>
              </span>
            </label>
          </Card>
        </TabsContent>
      </Tabs>
      <div className="mt-6">
        <Disclaimer />
      </div>
    </>
  );
}
