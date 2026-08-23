import type { ReactNode } from "react";

export function PageShell({ children }: { children: ReactNode }) {
  return <div className="inneros-page-shell">{children}</div>;
}
