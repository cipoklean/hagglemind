import { defineConfig } from 'vite'

export default defineConfig({
  root: '.',
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  // No React plugin - we're serving a vanilla JS single-file HTML
})
