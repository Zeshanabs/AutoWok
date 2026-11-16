import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "@/components/confirm-dialog";

function Harness({ onCancel }: { onCancel?: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>Open dialog</button>
      <ConfirmDialog
        open={open}
        title="Reject output?"
        confirmLabel="Reject"
        // A new function on every render, as real pages pass it.
        onCancel={() => {
          onCancel?.();
          setOpen(false);
        }}
        onConfirm={() => undefined}
      >
        <textarea aria-label="Reason" value={text} onChange={(event) => setText(event.target.value)} />
      </ConfirmDialog>
    </div>
  );
}

afterEach(cleanup);

describe("modal keyboard behaviour", () => {
  it("moves focus into the dialog and returns it to the opener on close", () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open dialog" });
    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("does not steal focus from a field when the parent re-renders", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    const field = screen.getByLabelText("Reason");
    field.focus();
    fireEvent.change(field, { target: { value: "Off brand" } });
    expect(document.activeElement).toBe(field);
    expect((field as HTMLTextAreaElement).value).toBe("Off brand");
  });

  it("keeps Tab inside the dialog", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    const confirm = screen.getByRole("button", { name: "Reject" });
    confirm.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByLabelText("Reason"));
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);
  });

  it("labels the dialog with its title", () => {
    const onCancel = vi.fn();
    render(<Harness onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    expect(screen.getByRole("dialog", { name: "Reject output?" })).toBeTruthy();
  });
});
