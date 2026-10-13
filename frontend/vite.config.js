import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import proxyOptions from './proxyOptions.js'

// `--mode demo` builds the public demo (GitHub Pages): sample data instead of a Frappe site.
export default defineConfig(({ mode }) => {
	const demo = mode === 'demo'
	return {
		plugins: [react(), tailwindcss()],
		base: demo ? process.env.DEMO_BASE || '/Teams-Notify/' : undefined,
		server: {
			port: 8082,
			host: '0.0.0.0',
			proxy: demo ? undefined : proxyOptions,
		},
		resolve: {
			alias: {
				'@': path.resolve(import.meta.dirname, 'src'),
				...(demo && { 'frappe-react-sdk': path.resolve(import.meta.dirname, 'src/demo/sdk.jsx') }),
			},
		},
		build: {
			outDir: demo ? 'dist-demo' : '../notification_engine/public/frontend',
			emptyOutDir: true,
			target: 'es2015',
		},
	}
})
