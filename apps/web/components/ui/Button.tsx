import type { ButtonHTMLAttributes } from "react";

const VARIANTS = {
  primary: "bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-300",
  outline:
    "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 disabled:text-slate-300 disabled:hover:bg-white",
  ghost: "text-slate-600 hover:bg-slate-100 disabled:text-slate-300",
} as const;

export type ButtonVariant = keyof typeof VARIANTS;

/** Shared classes — also usable on <Link> elements styled as buttons. */
export function buttonClasses(variant: ButtonVariant = "primary"): string {
  return `inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]}`;
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({ variant = "primary", className = "", type = "button", ...props }: ButtonProps) {
  return <button type={type} className={`${buttonClasses(variant)} ${className}`.trim()} {...props} />;
}
