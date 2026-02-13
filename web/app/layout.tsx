import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "Tdarr Sync Dashboard",
  description: "Monitor Tdarr Sync activity and trigger runs.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="header">
          <h1>Tdarr Sync Dashboard</h1>
          <p className="subtitle">Monitor Sonarr/Radarr ➜ Tdarr ➜ Library operations</p>
        </header>
        <main className="container">{children}</main>
        <footer className="footer">© {new Date().getFullYear()} Tdarr Sync</footer>
      </body>
    </html>
  );
}
