export const environment = {
  production: true,
  // Relative path: the production Nginx image proxies /api/ to the backend
  // service inside the Docker network, so the browser never needs the
  // backend's real host/port.
  apiBaseUrl: '/api/v1'
};
