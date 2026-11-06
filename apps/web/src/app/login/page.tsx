import { Suspense } from "react";
import { AuthLayout } from "@/components/auth/auth-layout";
import { pageMeta } from "@/lib/seo";
import { DemoAccess } from "./demo-access";
import { LoginFlow } from "./login-flow";

export const metadata = {
  ...pageMeta({ title: "Log in", description: "Sign in to the platform.", path: "/login" }),
  robots: { index: false, follow: false },
};

export default function LoginPage() {
  return (
    <AuthLayout title="Log in" intro="Sign in to see incidents and alerts for your sites.">
      <DemoAccess />
      <Suspense>
        <LoginFlow />
      </Suspense>
    </AuthLayout>
  );
}
