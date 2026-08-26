/** @type {import('next').NextConfig} */
const backendUrl = process.env.GAME_CHANGER_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
