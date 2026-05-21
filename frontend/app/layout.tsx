import "./globals.css";

export const metadata = {
  title: "Research Code",
  description: "Generate paper reports and runnable code scaffolds.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
