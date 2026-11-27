export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8010/api/v1',
  // Local dev already has the "Quick sign in" dev-login button; the public
  // demo button is prod-only (see environment.prod.ts).
  demoLogin: null as { email: string; password: string } | null
};
