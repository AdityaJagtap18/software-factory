import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { OrganizationSummary } from '../auth/auth.models';

const ACTIVE_ORG_KEY = 'sf_active_org_id';

@Injectable({ providedIn: 'root' })
export class OrganizationService {
  private readonly http = inject(HttpClient);

  readonly organizations = signal<OrganizationSummary[]>([]);
  readonly activeOrgId = signal<string | null>(localStorage.getItem(ACTIVE_ORG_KEY));

  listMine(): Observable<OrganizationSummary[]> {
    return this.http
      .get<OrganizationSummary[]>(`${environment.apiBaseUrl}/organizations`)
      .pipe(
        tap((orgs) => {
          this.organizations.set(orgs);
          // activeOrgId is seeded from localStorage, which is scoped to the
          // browser, not the logged-in account -- switching accounts in the
          // same browser (or an org being removed/moved) can leave it
          // pointing at an org this user isn't a member of, so every
          // org-scoped fetch (projects, etc.) silently queries the wrong
          // org while anything that isn't org-scoped looks fine. Validate it
          // against this account's real orgs on every fetch, not just when
          // it's unset.
          const current = this.activeOrgId();
          const stillValid = !!current && orgs.some((o) => o.id === current);
          if (!stillValid && orgs.length > 0) {
            this.setActiveOrg(orgs[0].id);
          }
        })
      );
  }

  create(name: string): Observable<OrganizationSummary> {
    return this.http
      .post<OrganizationSummary>(`${environment.apiBaseUrl}/organizations`, { name })
      .pipe(
        tap((org) => {
          this.organizations.update((list) => [...list, org]);
          this.setActiveOrg(org.id);
        })
      );
  }

  setActiveOrg(orgId: string): void {
    this.activeOrgId.set(orgId);
    localStorage.setItem(ACTIVE_ORG_KEY, orgId);
  }
}
