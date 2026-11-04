import * as React from "react";
import { cn } from "@/lib/utils";

const control =
  "block w-full rounded-control border border-slate-300 bg-white px-3.5 text-body text-ink placeholder:text-slate-500 transition-colors focus-visible:border-brand-500 disabled:bg-slate-100 aria-[invalid=true]:border-danger";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn(control, "h-11", className)} {...props} />,
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(control, "min-h-28 py-2.5", className)} {...props} />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        control,
        "h-11 appearance-none bg-[length:16px] bg-[right_0.75rem_center] bg-no-repeat pr-9",
        className,
      )}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%235f6e85' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
      }}
      {...props}
    >
      {children}
    </select>
  ),
);
Select.displayName = "Select";

export const Checkbox = React.forwardRef<
  HTMLInputElement,
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    type="checkbox"
    className={cn("mt-1 size-4 shrink-0 rounded border-slate-400 accent-brand-600", className)}
    {...props}
  />
));
Checkbox.displayName = "Checkbox";

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1.5 block text-small font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && !error ? (
        <p id={`${htmlFor}-hint`} className="mt-1 text-caption text-slate-600">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${htmlFor}-error`} role="alert" className="mt-1 text-caption text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
