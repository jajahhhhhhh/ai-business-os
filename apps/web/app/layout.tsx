import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AI Business OS — howtoniksen",
    template: "%s · AI Business OS",
  },
  description:
    "ศูนย์ควบคุมธุรกิจวิลล่าเกาะสมุย — งานรีโนเวท ลูกค้า คู่แข่ง คลังความรู้ และเอเจนต์ AI ในหน้าจอเดียว",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="th">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
