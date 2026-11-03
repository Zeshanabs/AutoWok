"use client";

import { useParams } from "next/navigation";

import { BrandSectionPage } from "@/components/brand-section";

const availableSections = [
  "voice",
  "audiences",
  "pillars",
  "goals",
  "policies",
] as const;

type Section = (typeof availableSections)[number];

export default function BrandSectionRoute() {
  const { brandId, section } = useParams<{
    brandId: string;
    section: string;
  }>();
  if (!availableSections.includes(section as Section)) {
    return <p className="p-8">Brand section not found.</p>;
  }
  return (
    <BrandSectionPage
      brandId={brandId}
      section={section as Section}
    />
  );
}
