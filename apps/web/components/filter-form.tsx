"use client";

import { useEffect, useRef } from "react";

/**
 * A GET form that, with JavaScript, submits itself as soon as a radio is
 * picked — the desktop rail, where an extra "Apply" for a single choice is a
 * wasted click. Without JavaScript it is an ordinary form with a button.
 */
export function FilterForm({
  autoSubmit = false,
  ...props
}: React.ComponentProps<"form"> & { autoSubmit?: boolean }) {
  const ref = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const form = ref.current;
    if (!autoSubmit || !form) return;
    // The native event, not React's onChange: React fires that on every
    // keystroke in the price fields, which must wait for the button.
    const onChange = (event: Event) => {
      if ((event.target as HTMLInputElement).type === "radio") form.requestSubmit();
    };
    form.addEventListener("change", onChange);
    return () => form.removeEventListener("change", onChange);
  }, [autoSubmit]);

  return <form ref={ref} method="get" {...props} />;
}
