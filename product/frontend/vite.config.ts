import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({ plugins: [react()], build: { sourcemap: false }, server: { host: '127.0.0.1', port: 5173, proxy: { '/api': { target: process.env.API_TARGET ?? 'http://127.0.0.1:8902', changeOrigin: false } } } });
