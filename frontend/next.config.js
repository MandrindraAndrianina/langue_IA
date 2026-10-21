/** @type {import('next').NextConfig} */
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");
const isDev = process.env.NODE_ENV !== "production";

// Next.js injecte du script inline (hydratation) : 'unsafe-inline' reste nécessaire.
// En développement, le rechargement à chaud utilise eval() et un WebSocket local.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob: ${API_URL}`,
  "font-src 'self' data:",
  `connect-src 'self' ${API_URL}${isDev ? " ws://localhost:* http://localhost:*" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
];

// HSTS n'a de sens qu'en HTTPS (production derrière TLS).
if (!isDev) {
  securityHeaders.push({ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" });
}

module.exports = {
  output: "standalone",
  // Les tests E2E lancent leur propre `next dev` : un dossier de build séparé
  // évite qu'il écrase celui du serveur de développement (ChunkLoadError).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};
