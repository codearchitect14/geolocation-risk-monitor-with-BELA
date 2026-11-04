import { Suspense } from "react";
import { AuthLayout } from "@/components/auth/auth-layout";
import { ResetForm } from "./reset-form";

export const metadata = { title: "Choose a new password", robots: { index: false, follow: false } };

export default function ResetPasswordPage() {
  return (
    <AuthLayout
      title="Choose a new password"
      intro="Use a long passphrase that you do not use anywhere else."
    >
      <Suspense>
        <ResetForm />
      </Suspense>
    </AuthLayout>
  );
}
