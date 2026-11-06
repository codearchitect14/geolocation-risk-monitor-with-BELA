/** Shown on demonstration deployments only (NEXT_PUBLIC_DEMO_MODE=1 at build time). */
export function DemoAccess() {
  if (process.env.NEXT_PUBLIC_DEMO_MODE !== "1") return null;
  const viewer = process.env.NEXT_PUBLIC_DEMO_VIEWER;
  const password = process.env.NEXT_PUBLIC_DEMO_PASSWORD;
  return (
    <aside
      aria-labelledby="demo-access"
      className="mb-6 rounded-card border border-brand-100 bg-brand-100/40 p-4 text-small"
    >
      <h2 id="demo-access" className="font-semibold text-ink">
        Demonstration environment
      </h2>
      <p className="mt-1 text-slate-700">
        Everything here is synthetic or illustrative: the sites, the portfolio, and the revenue history.
        Incidents come from a recorded public earthquake feed, re-timed for the demonstration.
      </p>
      <p className="mt-2 text-slate-700">
        The public demonstration uses a read-only viewer account.
        {viewer ? (
          <>
            {" "}
            Email <span className="font-mono text-ink">{viewer}</span>
            {password ? (
              <>
                , password <span className="font-mono text-ink">{password}</span>.
              </>
            ) : (
              <>
                . The password is printed once when the demonstration is set up (
                <span className="font-mono">make demo</span>).
              </>
            )}
          </>
        ) : null}
      </p>
      <p className="mt-2 text-slate-700">
        Accounts for the analyst, manager, tenant administrator, platform administrator, and finance roles are
        created at the same time. Administrator accounts ask you to set up an authenticator app at first
        sign-in.
      </p>
    </aside>
  );
}
