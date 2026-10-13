// `yarn dev` serves the dashboard on :8082 and sends API calls to the site.
// Change TARGET / SITE for your bench: TARGET is the port that serves the site
// (nginx port or `bench serve` port), SITE is the site name. Frappe picks the
// site from the Host header, so it is forced here.
const TARGET = process.env.FRAPPE_TARGET || 'http://127.0.0.1:8003'
const SITE = process.env.FRAPPE_SITE || 'teamsnotify.com'

export default {
	// `login` too: Frappe redirects signed-out users to /login, which must reach the backend.
	'^/(app|login|api|assets|files|private)': {
		target: TARGET,
		ws: true,
		changeOrigin: true,
		headers: { Host: SITE },
	},
}
