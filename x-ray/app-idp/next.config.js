/** @type {import('next').NextConfig} */
const nextConfig = {
  // ALB forwards the full path unchanged ("/idp/*"), so the app itself must
  // handle requests under that prefix rather than at its own root.
  basePath: "/idp",
  reactStrictMode: true,
};

module.exports = nextConfig;
