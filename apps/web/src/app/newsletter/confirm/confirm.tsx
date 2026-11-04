"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function Confirm() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<"busy" | "ok" | "bad">("busy");
  useEffect(() => {
    if (!token) return setState("bad");
    api("/newsletter/confirm", { method: "POST", body: { token } }).then(
      () => setState("ok"),
      () => setState("bad"),
    );
  }, [token]);
  if (state === "busy") return <p role="status">Confirming</p>;
  if (state === "ok")
    return (
      <p role="status" className="text-[1.125rem]">
        Your subscription is confirmed. Thank you.
      </p>
    );
  return (
    <p role="alert" className="text-danger">
      This confirmation link is not valid. Subscribe again from the footer to receive a new link.
    </p>
  );
}
