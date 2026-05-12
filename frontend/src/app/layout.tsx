import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono, Chivo } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { Toaster } from "sonner";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"], weight: ["400","500","600","700"],
  variable: "--font-plex-sans", display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"], weight: ["400","500","600"],
  variable: "--font-plex-mono", display: "swap",
});
const chivo = Chivo({
  subsets: ["latin"], weight: ["400","600","700","800","900"],
  variable: "--font-chivo", display: "swap",
});

export const metadata: Metadata = {
  title: "Prosper · Tokenized yield on Stellar",
  description: "Regulated tokenized-yield platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // SSR-safe theme: read cookie on server so the first paint matches the user's preference.
  const themeCookie = cookies().get("prosper_theme")?.value;
  const theme = themeCookie === "dark" ? "dark" : "light";
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable} ${chivo.variable} ${theme}`}>
      <body className="font-sans antialiased">
        {children}
        <Toaster position="top-right" theme={theme as "light" | "dark"} />
      </body>
    </html>
  );
}
