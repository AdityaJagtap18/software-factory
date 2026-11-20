import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthUser, TokenResponse } from './auth.models';

const ACCESS_TOKEN_KEY = 'sf_access_token';
const REFRESH_TOKEN_KEY = 'sf_refresh_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  readonly currentUser = signal<AuthUser | null>(null);
  readonly initializing = signal<boolean>(true);

  get accessToken(): string | null {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  }

  get refreshToken(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  get isAuthenticated(): boolean {
    return !!this.accessToken;
  }

  register(email: string, password: string, fullName: string): Observable<AuthUser> {
    return this.http.post<AuthUser>(`${environment.apiBaseUrl}/auth/register`, {
      email,
      password,
      full_name: fullName
    });
  }

  login(email: string, password: string): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${environment.apiBaseUrl}/auth/login`, { email, password })
      .pipe(tap((tokens) => this.storeTokens(tokens)));
  }

  /** Local-dev convenience: whether the backend has a quick sign-in account
   * configured, and its display name if so. Returns unavailable on any
   * error so a disabled/missing endpoint never breaks the login page. */
  devLoginStatus(): Observable<{ available: boolean; display_name?: string }> {
    return this.http.get<{ available: boolean; display_name?: string }>(
      `${environment.apiBaseUrl}/auth/dev-login`
    );
  }

  devLogin(): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${environment.apiBaseUrl}/auth/dev-login`, {})
      .pipe(tap((tokens) => this.storeTokens(tokens)));
  }

  fetchCurrentUser(): Observable<AuthUser> {
    return this.http
      .get<AuthUser>(`${environment.apiBaseUrl}/auth/me`)
      .pipe(tap((user) => this.currentUser.set(user)));
  }

  refresh(): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${environment.apiBaseUrl}/auth/refresh`, {
        refresh_token: this.refreshToken
      })
      .pipe(tap((tokens) => this.storeTokens(tokens)));
  }

  logout(): void {
    const refreshToken = this.refreshToken;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    this.currentUser.set(null);
    if (refreshToken) {
      this.http
        .post(`${environment.apiBaseUrl}/auth/logout`, { refresh_token: refreshToken })
        .subscribe({ error: () => void 0 });
    }
  }

  private storeTokens(tokens: TokenResponse): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
  }
}
