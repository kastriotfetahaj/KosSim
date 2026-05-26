import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";
import { SiteHeader } from "@/components/SiteHeader";
import { Breadcrumb } from "@/components/Breadcrumb";
import Link from "next/link";

const saiba45 = localFont({
  variable: "--font-saiba-45",
  src: "../fonts/saiba-45.ttf"
});

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Gitter",
  description: "Your code sharing platform",
  icons: {
    icon: "/favicon.png",
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${spaceGrotesk.variable} ${saiba45.variable} antialiased font-[family-name:var(--font-space-grotesk)]`}
      >
        <div className="flex flex-col bg-sleek-background text-slate-50 h-screen overflow-hidden">
          <SiteHeader>
            <div className="flex items-center px-3 test bg-black pr-10">
              <Link href="/">
                <h1 className="text-4xl font-bold p-2 font-saiba text-white">gitter</h1>
              </Link>
            </div>
          </SiteHeader>
          <Breadcrumb />
          <div className="flex flex-row flex-1 overflow-y-auto">{children}</div>
        </div>
      </body>
    </html>
  );
}
