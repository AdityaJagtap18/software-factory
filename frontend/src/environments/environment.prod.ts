export const environment = {
  production: true,
  // Relative path: the production Nginx image proxies /api/ to the backend
  // service inside the Docker network, so the browser never needs the
  // backend's real host/port.
  apiBaseUrl: '/api/v1',
  // Public, deliberately shared demo account (see VPS_DEPLOYMENT_PLAYBOOK /
  // deploy notes) -- a real password login, not a backend auth bypass. Its
  // org's projects are wiped nightly by a cron job on the VPS.
  demoLogin: { email: 'demo@example.com', password: 'Demo#Factory2026' }
};
