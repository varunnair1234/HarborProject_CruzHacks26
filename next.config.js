/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'export', // Export as static HTML/CSS/JS for GitHub Pages
  images: {
    unoptimized: true, // Required for static export
  },
  // Set base path if deploying to a subdirectory (e.g., /HarborProject_CruzHacks26)
  // basePath: process.env.NODE_ENV === 'production' ? '/HarborProject_CruzHacks26' : '',
  // assetPrefix: process.env.NODE_ENV === 'production' ? '/HarborProject_CruzHacks26' : '',
}

module.exports = nextConfig
