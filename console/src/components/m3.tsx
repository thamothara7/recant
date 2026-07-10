import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";

// Shared Material 3 primitives. Every component uses these instead of
// hand-rolling buttons/icons so the whole console speaks one M3 dialect.
// Tokens only; no raw hex values anywhere in components.

export function Icon({
  name,
  size = 20,
  fill = false,
  className = "",
  style,
}: {
  name: string;
  size?: number;
  fill?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      aria-hidden
      className={`msr ${fill ? "msr-fill" : ""} ${className}`}
      style={{ fontSize: size, ...style }}
    >
      {name}
    </span>
  );
}

type ButtonVariant = "filled" | "tonal" | "outlined" | "text" | "elevated";
type ButtonTone = "primary" | "error";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  filled: "",
  tonal: "bg-secondary-container text-on-secondary-container",
  outlined: "border border-outline text-primary bg-transparent",
  text: "text-primary bg-transparent",
  elevated: "bg-surface-container-low text-primary shadow-elevation-1",
};

// M3 common button: 40px tall, pill shape, label-large, state layer.
export function Button({
  variant = "filled",
  tone = "primary",
  icon,
  children,
  className = "",
  disabled,
  ...rest
}: {
  variant?: ButtonVariant;
  tone?: ButtonTone;
  icon?: string;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const filledStyle =
    variant === "filled"
      ? tone === "error"
        ? { background: "var(--md-error)", color: "var(--md-on-error)" }
        : { background: "var(--md-primary)", color: "var(--md-on-primary)" }
      : undefined;
  return (
    <button
      disabled={disabled}
      className={`state-layer inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-full text-label-lg font-medium transition-colors ${
        icon ? "pl-4 pr-6" : "px-6"
      } ${VARIANT_CLASSES[variant]} ${
        disabled ? "pointer-events-none opacity-40" : ""
      } ${className}`}
      style={filledStyle}
      {...rest}
    >
      {icon && <Icon name={icon} size={18} />}
      {children}
    </button>
  );
}

// M3 icon button: 40x40 round target, 24px icon.
export function IconButton({
  icon,
  label,
  selected = false,
  size = 22,
  className = "",
  ...rest
}: {
  icon: string;
  label: string;
  selected?: boolean;
  size?: number;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      aria-label={label}
      title={label}
      aria-pressed={selected}
      className={`state-layer inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
        selected ? "bg-secondary-container text-on-secondary-container" : "text-on-surface-variant"
      } ${className}`}
      {...rest}
    >
      <Icon name={icon} size={size} fill={selected} />
    </button>
  );
}

// M3 assist/status chip: 24px tall tonal chip with a leading icon. Pass the
// container/onContainer pair (e.g. from STATUS_META) via style for status
// chips, or leave default for neutral chips.
export function Chip({
  icon,
  label,
  container = "var(--md-surface-container-highest)",
  onContainer = "var(--md-on-surface-variant)",
  className = "",
  mono = false,
}: {
  icon?: string;
  label: string;
  container?: string;
  onContainer?: string;
  className?: string;
  mono?: boolean;
}) {
  return (
    <span
      className={`inline-flex h-6 items-center gap-1 rounded-md3-sm px-2 text-label-md font-medium ${
        mono ? "mono" : ""
      } ${className}`}
      style={{ background: container, color: onContainer }}
    >
      {icon && <Icon name={icon} size={14} fill />}
      {label}
    </span>
  );
}
