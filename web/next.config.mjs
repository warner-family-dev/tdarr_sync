const stripTrailing = (value) => value.replace(/\/+$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const origin = process.env.NEXT_BACKEND_ORIGIN || "http://api:8000";
    const normalizedOrigin = stripTrailing(origin);

    return [
      {
        source: "/tdarr-api/:path*",
        destination: `${normalizedOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
