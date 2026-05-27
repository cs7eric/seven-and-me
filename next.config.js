/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    serverComponentsExternalPackages: [
      'torch',
      'torchaudio',
      'transformers',
      'soundfile',
      'scipy',
    ],
  },
};

module.exports = nextConfig;