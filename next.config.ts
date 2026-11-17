import type { NextConfig } from 'next';
const config: NextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  experimental: { agentUpgrade: 'security' },
};
export default config;
