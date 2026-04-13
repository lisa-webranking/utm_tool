import * as React from "react";

type CollapsibleContextValue = {
  open: boolean;
  setOpen: (next: boolean) => void;
};

const CollapsibleContext = React.createContext<CollapsibleContextValue | null>(null);

type CollapsibleProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
  children: React.ReactNode;
};

export function Collapsible({
  open,
  defaultOpen = false,
  onOpenChange,
  className,
  children,
}: CollapsibleProps) {
  const [internalOpen, setInternalOpen] = React.useState(defaultOpen);
  const isControlled = typeof open === "boolean";
  const currentOpen = isControlled ? open : internalOpen;

  const setOpen = (next: boolean) => {
    if (!isControlled) {
      setInternalOpen(next);
    }
    onOpenChange?.(next);
  };

  return (
    <CollapsibleContext.Provider value={{ open: currentOpen, setOpen }}>
      <div className={className}>{children}</div>
    </CollapsibleContext.Provider>
  );
}

type CollapsibleTriggerProps = React.ButtonHTMLAttributes<HTMLButtonElement>;

export function CollapsibleTrigger({
  onClick,
  type = "button",
  children,
  ...props
}: CollapsibleTriggerProps) {
  const context = React.useContext(CollapsibleContext);

  if (!context) {
    throw new Error("CollapsibleTrigger must be used within Collapsible");
  }

  return (
    <button
      type={type}
      aria-expanded={context.open}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          context.setOpen(!context.open);
        }
      }}
      {...props}
    >
      {children}
    </button>
  );
}

type CollapsibleContentProps = React.HTMLAttributes<HTMLDivElement>;

export function CollapsibleContent({ children, ...props }: CollapsibleContentProps) {
  const context = React.useContext(CollapsibleContext);

  if (!context) {
    throw new Error("CollapsibleContent must be used within Collapsible");
  }

  if (!context.open) {
    return null;
  }

  return <div {...props}>{children}</div>;
}
