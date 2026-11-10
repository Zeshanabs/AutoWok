/* eslint-disable @next/next/no-img-element -- authenticated API media cannot use next/image optimization */
import { mediaUrl, type MediaAsset, type PreviewMediaItem } from "@/lib/media-types";

type Props = {
  asset: Pick<MediaAsset, "media_type" | "content_url" | "thumbnail_url" | "original_filename" | "title"> | PreviewMediaItem;
  className?: string;
  controls?: boolean;
};

export function MediaThumbnail({ asset, className = "", controls = false }: Props) {
  const label = "original_filename" in asset ? asset.title || asset.original_filename : asset.title;
  if (asset.media_type === "video") {
    return (
      <video
        className={`bg-slate-900 object-cover ${className}`}
        src={mediaUrl(asset.content_url)}
        controls={controls}
        muted
        playsInline
        preload="metadata"
        aria-label={label}
      />
    );
  }
  return (
    <img
      className={`bg-slate-100 object-cover ${className}`}
      src={mediaUrl(asset.thumbnail_url ?? asset.content_url)}
      alt={label}
      loading="lazy"
    />
  );
}
