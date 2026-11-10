"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { MediaThumbnail } from "@/components/media-thumbnail";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest, uploadWithProgress } from "@/lib/api";
import type { Brand } from "@/lib/brand-types";
import { ACCEPTED_MEDIA, formatBytes, formatDuration, type MediaAsset } from "@/lib/media-types";

type UploadItem = { name: string; progress: number; status: "uploading" | "done" | "error"; message?: string };

const fieldClass = "rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500";

export default function MediaLibraryPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [view, setView] = useState<"grid" | "list">("grid");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [brandFilter, setBrandFilter] = useState("");
  const [uploadBrand, setUploadBrand] = useState("");
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [archiveTarget, setArchiveTarget] = useState<MediaAsset | null>(null);
  const [archiving, setArchiving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    const params = new URLSearchParams({ workspace_id: workspaceId });
    if (typeFilter) params.set("media_type", typeFilter);
    if (brandFilter) params.set("brand_id", brandFilter);
    if (search.trim()) params.set("search", search.trim());
    try {
      const [assetData, brandData] = await Promise.all([
        apiRequest<MediaAsset[]>(`/media-assets?${params.toString()}`),
        apiRequest<Brand[]>(`/workspaces/${workspaceId}/brands`),
      ]);
      setAssets(assetData);
      setBrands(brandData);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "The media library could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, typeFilter, brandFilter, search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), search ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [load, search]);

  const onFiles = async (files: FileList | null) => {
    if (!files || !workspaceId) return;
    setNotice(null);
    const list = Array.from(files);
    setUploads(list.map((file) => ({ name: file.name, progress: 0, status: "uploading" })));
    let succeeded = 0;
    for (const [index, file] of list.entries()) {
      const form = new FormData();
      form.set("workspace_id", workspaceId);
      if (uploadBrand) form.set("brand_id", uploadBrand);
      form.set("file", file);
      try {
        const asset = await uploadWithProgress<MediaAsset>("/media-assets/upload", form, (progress) =>
          setUploads((current) => current.map((item, i) => (i === index ? { ...item, progress } : item))),
        );
        succeeded += 1;
        setUploads((current) =>
          current.map((item, i) =>
            i === index
              ? { ...item, progress: 1, status: "done", message: asset.duplicate ? "Already in library" : "Uploaded" }
              : item,
          ),
        );
      } catch (uploadError) {
        setUploads((current) =>
          current.map((item, i) =>
            i === index
              ? { ...item, status: "error", message: uploadError instanceof ApiError ? uploadError.message : "Upload failed." }
              : item,
          ),
        );
      }
    }
    if (fileInput.current) fileInput.current.value = "";
    if (succeeded) setNotice(`${succeeded} file(s) added to the library.`);
    await load();
  };

  const archive = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await apiRequest(`/media-assets/${archiveTarget.id}`, { method: "DELETE" });
      setNotice(`${archiveTarget.title || archiveTarget.original_filename} was archived.`);
      setArchiveTarget(null);
      await load();
    } catch (archiveError) {
      setError(archiveError instanceof ApiError ? archiveError.message : "The asset could not be archived.");
      setArchiveTarget(null);
    } finally {
      setArchiving(false);
    }
  };

  const brandName = (id: string | null) => brands.find((brand) => brand.id === id)?.name;

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">Media</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Media library</h1>
            <p className="mt-1 text-sm text-slate-600">
              JPG, PNG, GIF images and MP4/MOV videos. Location and camera metadata is removed from photos on upload.
            </p>
          </div>
          {workspaceId && (
            <div className="flex flex-wrap items-center gap-2">
              <select aria-label="Brand for uploads" className={fieldClass} value={uploadBrand} onChange={(e) => setUploadBrand(e.target.value)}>
                <option value="">No brand</option>
                {brands.map((brand) => (
                  <option key={brand.id} value={brand.id}>{brand.name}</option>
                ))}
              </select>
              <input ref={fileInput} type="file" multiple accept={ACCEPTED_MEDIA} className="hidden" onChange={(e) => void onFiles(e.target.files)} />
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                disabled={uploads.some((item) => item.status === "uploading")}
                className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:bg-slate-300"
              >
                Upload media
              </button>
            </div>
          )}
        </div>

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace to manage media.</p>
        ) : (
          <>
            {uploads.length > 0 && (
              <ul className="mt-6 space-y-2 rounded-2xl border border-slate-200 bg-white p-4" aria-label="Upload progress">
                {uploads.map((item, index) => (
                  <li key={`${item.name}-${index}`} className="text-sm">
                    <div className="flex justify-between gap-2">
                      <span className="truncate">{item.name}</span>
                      <span className={item.status === "error" ? "text-red-700" : "text-slate-500"}>
                        {item.status === "uploading" ? `${Math.round(item.progress * 100)}%` : item.message}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded bg-slate-100">
                      <div
                        className={`h-full ${item.status === "error" ? "bg-red-500" : "bg-indigo-500"}`}
                        style={{ width: `${Math.round((item.status === "error" ? 1 : item.progress) * 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-6 flex flex-wrap items-center gap-2">
              <input aria-label="Search media" placeholder="Search by name" className={`${fieldClass} min-w-0 flex-1 sm:max-w-xs`} value={search} onChange={(e) => setSearch(e.target.value)} />
              <select aria-label="Filter by type" className={fieldClass} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">All types</option>
                <option value="image">Images</option>
                <option value="video">Videos</option>
              </select>
              <select aria-label="Filter by brand" className={fieldClass} value={brandFilter} onChange={(e) => setBrandFilter(e.target.value)}>
                <option value="">All brands</option>
                {brands.map((brand) => (
                  <option key={brand.id} value={brand.id}>{brand.name}</option>
                ))}
              </select>
              <div className="ml-auto flex rounded-xl border border-slate-300 bg-white p-0.5 text-sm" role="group" aria-label="View">
                {(["grid", "list"] as const).map((mode) => (
                  <button key={mode} type="button" aria-pressed={view === mode} onClick={() => setView(mode)} className={`rounded-lg px-3 py-1.5 capitalize ${view === mode ? "bg-slate-900 text-white" : ""}`}>
                    {mode}
                  </button>
                ))}
              </div>
            </div>

            {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
            {notice && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}

            {loading && assets.length === 0 ? (
              <p className="mt-6 text-sm text-slate-500">Loading media…</p>
            ) : assets.length === 0 ? (
              <div className="mt-6 rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-600">
                {search || typeFilter || brandFilter ? "No media matches these filters." : "No media yet. Upload images or videos to attach them to posts."}
              </div>
            ) : view === "grid" ? (
              <ul className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                {assets.map((asset) => (
                  <li key={asset.id} className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
                    <Link href={`/dashboard/media/${asset.id}`} className="block focus:outline-none focus:ring-2 focus:ring-indigo-500">
                      <MediaThumbnail asset={asset} className="aspect-square w-full" />
                      <div className="p-3 text-sm">
                        <p className="truncate font-medium">{asset.title || asset.original_filename}</p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {asset.file_extension.toUpperCase()} · {formatBytes(asset.file_size)}
                          {asset.duration_seconds != null && ` · ${formatDuration(asset.duration_seconds)}`}
                        </p>
                        {brandName(asset.brand_id) && <p className="mt-0.5 truncate text-xs text-indigo-700">{brandName(asset.brand_id)}</p>}
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="mt-6 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="p-3">File</th><th className="p-3">Type</th><th className="p-3">Size</th><th className="p-3">Brand</th><th className="p-3">Uploaded</th><th className="p-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {assets.map((asset) => (
                      <tr key={asset.id} className="border-t border-slate-100">
                        <td className="p-3">
                          <Link href={`/dashboard/media/${asset.id}`} className="flex items-center gap-3 font-medium hover:text-indigo-700">
                            <MediaThumbnail asset={asset} className="h-10 w-10 shrink-0 rounded-lg" />
                            <span className="truncate">{asset.title || asset.original_filename}</span>
                          </Link>
                        </td>
                        <td className="p-3">{asset.mime_type}</td>
                        <td className="p-3">{formatBytes(asset.file_size)}</td>
                        <td className="p-3">{brandName(asset.brand_id) ?? "—"}</td>
                        <td className="p-3">{new Date(asset.created_at).toLocaleDateString()}</td>
                        <td className="p-3 text-right">
                          <button type="button" onClick={() => setArchiveTarget(asset)} className="text-sm font-medium text-red-700">Archive</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <ConfirmDialog
          open={archiveTarget !== null}
          title="Archive this media?"
          confirmLabel="Archive"
          tone="danger"
          busy={archiving}
          onCancel={() => setArchiveTarget(null)}
          onConfirm={() => void archive()}
        >
          <p>
            {archiveTarget?.title || archiveTarget?.original_filename} will be removed from the library. Posts that still
            reference it will fail validation until the media is replaced.
          </p>
        </ConfirmDialog>
      </AppShell>
    </ProtectedPage>
  );
}
