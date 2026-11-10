import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PostPreview } from "@/components/post-preview";
import { StatusBadge, statusLabel } from "@/components/status-badge";
import { formatBytes, formatDuration, type DraftPreview } from "@/lib/media-types";

afterEach(cleanup);

const basePreview: DraftPreview = {
  platform: "instagram",
  preview_type: "carousel",
  approximate: true,
  disclaimer: "This preview is an approximation.",
  media_count: 2,
  caption: "Big news.\n\n#launch",
  caption_length: 18,
  account_name: "Autowok",
  account_username: "autowok",
  account_image_url: null,
  media: [
    { id: "a", media_type: "image", mime_type: "image/jpeg", title: "One", width: 1080, height: 1080, duration_seconds: null, content_url: "/api/v1/media-assets/a/content", thumbnail_url: "/api/v1/media-assets/a/thumbnail" },
    { id: "b", media_type: "image", mime_type: "image/jpeg", title: "Two", width: 1080, height: 1080, duration_seconds: null, content_url: "/api/v1/media-assets/b/content", thumbnail_url: null },
  ],
  errors: [],
  warnings: [],
};

describe("platform previews", () => {
  it("renders an Instagram carousel with slide navigation", () => {
    render(<PostPreview preview={basePreview} />);
    expect(screen.getByText("1/2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show item 2" }));
    expect(screen.getByText("2/2")).toBeTruthy();
    expect(screen.getByAltText("Two")).toBeTruthy();
  });

  it("renders a text-only Facebook post", () => {
    render(<PostPreview preview={{ ...basePreview, platform: "facebook", media: [], media_count: 0, account_name: "Autowok Page" }} />);
    expect(screen.getByText("Autowok Page")).toBeTruthy();
    expect(screen.getByText(/Big news/)).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("explains Instagram's media requirement when nothing is attached", () => {
    render(<PostPreview preview={{ ...basePreview, media: [], media_count: 0 }} />);
    expect(screen.getByText("Instagram requires an image or video.")).toBeTruthy();
  });
});

describe("publishing confirmation", () => {
  it("keeps the confirm button disabled until acknowledged", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(
      <ConfirmDialog open title="Publish immediately?" confirmLabel="Publish now" confirmDisabled onConfirm={onConfirm} onCancel={() => {}}>
        <p>Body</p>
      </ConfirmDialog>,
    );
    const button = screen.getByRole("button", { name: "Publish now" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    rerender(
      <ConfirmDialog open title="Publish immediately?" confirmLabel="Publish now" onConfirm={onConfirm} onCancel={() => {}}>
        <p>Body</p>
      </ConfirmDialog>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Publish now" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("closes on Escape", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open title="Cancel?" confirmLabel="Yes" onConfirm={() => {}} onCancel={onCancel}>
        <p>Body</p>
      </ConfirmDialog>,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledOnce();
  });
});

describe("status and formatting helpers", () => {
  it("labels statuses for people", () => {
    expect(statusLabel("ready_for_review")).toBe("Awaiting approval");
    expect(statusLabel("pending")).toBe("Queued");
    expect(statusLabel("published")).toBe("Published");
    render(<StatusBadge status="failed" />);
    expect(screen.getByText("Failed").className).toContain("bg-red-100");
  });

  it("formats sizes and durations", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatDuration(75)).toBe("1:15");
    expect(formatDuration(null)).toBeNull();
  });
});
