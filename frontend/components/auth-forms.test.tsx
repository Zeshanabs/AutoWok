import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/components/auth-provider";
import { LoginForm, RegisterForm } from "@/components/auth-forms";

vi.mock("@/components/auth-provider", () => ({
  useAuth: vi.fn(),
}));

const auth = {
  user: null,
  workspaces: [],
  selectedWorkspace: null,
  status: "unauthenticated" as const,
  error: null,
  refreshUser: vi.fn(async () => {}),
  selectWorkspace: vi.fn(async () => {}),
  login: vi.fn(async () => {}),
  register: vi.fn(async () => {}),
  logout: vi.fn(async () => {}),
} satisfies ReturnType<typeof useAuth>;

describe("authentication forms", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue(auth);
    auth.login.mockReset();
    auth.register.mockReset();
  });

  it("submits valid login data and displays authentication errors", async () => {
    auth.login.mockRejectedValue(new Error("Invalid email or password."));
    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(auth.login).toHaveBeenCalledWith(
        "user@example.com",
        "correct password",
      );
      expect(screen.getByRole("alert").textContent).toContain(
        "Invalid email or password.",
      );
    });
  });

  it("shows and hides the password field", () => {
    render(<LoginForm />);
    const password = screen.getByLabelText("Password", { exact: true });
    expect(password.getAttribute("type")).toBe("password");
    fireEvent.click(screen.getByLabelText("Show password"));
    expect(password.getAttribute("type")).toBe("text");
  });

  it("rejects mismatched registration passwords before making an API call", async () => {
    render(<RegisterForm />);
    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "Test User" },
    });
    fireEvent.change(screen.getByLabelText("Email", { exact: true }), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), {
      target: { value: "StrongPassword#1234" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "DifferentPassword#1234" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Passwords do not match.",
    );
    expect(auth.register).not.toHaveBeenCalled();
  });
});
