"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/field";
import { api, ApiError } from "@/lib/api";
import { industries } from "@/content/site";

// The strict content security policy has no script-eval; skip the library's attempt to compile validators with Function().
z.config({ jitless: true });

const schema = z.object({
  name: z.string().trim().min(1, "Enter your name.").max(100),
  email: z.string().trim().email("Enter a valid work email address.").max(254),
  company: z.string().trim().min(1, "Enter your organization.").max(150),
  role: z.string().trim().min(1, "Enter your role.").max(100),
  industry: z.string().min(1, "Choose an industry."),
  message: z.string().trim().max(2000, "Keep the message under 2,000 characters.").optional(),
  consent: z.boolean().refine((v) => v, "Consent is required so that we can reply."),
  website: z.string().max(200).optional(),
});
type Values = z.infer<typeof schema>;

export function DemoForm() {
  const params = useSearchParams();
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: params.get("email") ?? "",
      message: params.get("topic") === "security" ? "Security topic: " : "",
      consent: false,
    },
  });

  async function onSubmit(v: Values) {
    setError("");
    try {
      await api("/contact/demo-request", {
        method: "POST",
        body: {
          name: v.name,
          email: v.email,
          company: v.company,
          role: v.role,
          industry: v.industry,
          message: v.message || null,
          consent: v.consent,
          website: v.website || null,
        },
      });
      setDone(true);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 429
          ? "Too many requests from this address. Try again later."
          : "The request could not be sent. Check the fields and try again.",
      );
    }
  }

  if (done) {
    return (
      <div role="status" className="rounded-card border border-line bg-page p-8 text-center">
        <h2 className="text-h3">Thank you</h2>
        <p className="mt-2 text-slate-700">
          Your request was received. We will reply to the email address you provided.
        </p>
        <Button asChild className="mt-6" variant="secondary">
          <Link href="/">Back to the home page</Link>
        </Button>
      </div>
    );
  }

  return (
    <form method="post" onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-5 sm:grid-cols-2">
      <Field label="Name" htmlFor="name" error={errors.name?.message}>
        <Input
          id="name"
          autoComplete="name"
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? "name-error" : undefined}
          {...register("name")}
        />
      </Field>
      <Field label="Work email" htmlFor="email" error={errors.email?.message}>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "email-error" : undefined}
          {...register("email")}
        />
      </Field>
      <Field label="Organization" htmlFor="company" error={errors.company?.message}>
        <Input
          id="company"
          autoComplete="organization"
          aria-invalid={!!errors.company}
          aria-describedby={errors.company ? "company-error" : undefined}
          {...register("company")}
        />
      </Field>
      <Field label="Role" htmlFor="role" error={errors.role?.message}>
        <Input
          id="role"
          autoComplete="organization-title"
          aria-invalid={!!errors.role}
          aria-describedby={errors.role ? "role-error" : undefined}
          {...register("role")}
        />
      </Field>
      <Field label="Industry" htmlFor="industry" error={errors.industry?.message} className="sm:col-span-2">
        <Select
          id="industry"
          defaultValue=""
          aria-invalid={!!errors.industry}
          aria-describedby={errors.industry ? "industry-error" : undefined}
          {...register("industry")}
        >
          <option value="" disabled>
            Select an industry
          </option>
          {industries.map((i) => (
            <option key={i.slug} value={i.title}>
              {i.title}
            </option>
          ))}
          <option value="Other">Other</option>
        </Select>
      </Field>
      <Field
        label="Message (optional)"
        htmlFor="message"
        error={errors.message?.message}
        hint="For example, the number of sites and the regions you cover."
        className="sm:col-span-2"
      >
        <Textarea id="message" aria-describedby="message-hint" {...register("message")} />
      </Field>
      {/* Honeypot: hidden from people and assistive technology; bots that fill it are ignored by the server. */}
      <div className="absolute -left-[9999px]" aria-hidden="true">
        <label htmlFor="website">Website</label>
        <input id="website" tabIndex={-1} autoComplete="off" {...register("website")} />
      </div>
      <div className="sm:col-span-2">
        <label className="flex gap-3 text-small text-slate-700">
          <Checkbox
            aria-describedby={errors.consent ? "consent-error" : undefined}
            {...register("consent")}
          />
          <span>
            I agree that Meridian Signal may use these details to reply to this request, as described in the{" "}
            <Link href="/legal/privacy" className="text-brand-600 underline">
              privacy policy
            </Link>
            .
          </span>
        </label>
        {errors.consent ? (
          <p id="consent-error" role="alert" className="mt-1 text-caption text-danger">
            {errors.consent.message}
          </p>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-small text-danger sm:col-span-2">
          {error}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <Button type="submit" size="lg" disabled={isSubmitting}>
          {isSubmitting ? "Sending" : "Send request"}
        </Button>
      </div>
    </form>
  );
}
