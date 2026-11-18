import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk } from "next/font/google";
import { AuthProvider } from "@/components/auth-provider";
import { ErrorListener } from "@/components/error-listener";
import "./globals.css";

const bodyFont = Hanken_Grotesk({
  variable: "--font-body",
  subsets: ["latin"],
  display: "swap",
});

const displayFont = Bricolage_Grotesque({
  variable: "--font-display-face",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Autowok",
  description: "Plan, write, schedule and measure your Facebook and Instagram content in one place.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${bodyFont.variable} ${displayFont.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-slate-50 text-slate-900">
        <ErrorListener />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
