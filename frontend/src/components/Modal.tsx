import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

/** Full-screen sheet on phones, centered dialog from `sm`. Closes on Escape and backdrop click. */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-zinc-900/40" onClick={onClose} />
      <div
        className={`relative flex max-h-[100dvh] w-full flex-col bg-white shadow-xl sm:max-h-[90vh] sm:rounded-2xl ${wide ? "sm:max-w-2xl" : "sm:max-w-lg"}`}
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" aria-label="Close" onClick={onClose} className="-mr-2 rounded-lg p-2 hover:bg-zinc-100">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-5">{children}</div>
      </div>
    </div>
  );
}
