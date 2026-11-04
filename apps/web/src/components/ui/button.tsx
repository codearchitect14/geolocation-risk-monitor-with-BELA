import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-control font-medium transition-[background-color,box-shadow,transform,color] duration-200 ease-out disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-brand-600 text-white shadow-e1 hover:bg-[#1a52a6] active:translate-y-px",
        secondary: "border border-slate-300 bg-white text-ink hover:border-brand-500 hover:text-brand-600",
        ghost: "text-slate-700 hover:bg-slate-100 hover:text-ink",
        destructive: "bg-danger text-white hover:bg-[#a53125]",
        inverse: "bg-white text-ink hover:bg-brand-100",
        outlineInverse: "border border-white/40 text-white hover:bg-white/10",
      },
      size: {
        sm: "h-9 px-3 text-small",
        md: "h-11 px-5 text-body",
        lg: "h-12 px-6 text-body",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
  },
);
Button.displayName = "Button";
