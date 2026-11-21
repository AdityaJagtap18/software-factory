import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../mock-data.service';
import { NAV_ITEMS } from '../nav-items';
import { AuthService } from '../auth/auth.service';
import { OrganizationService } from '../org/organization.service';
import { NotificationService } from '../org/notification.service';

@Component({
  selector: 'sf-app-shell',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, RouterOutlet, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app-shell.component.html',
  styleUrl: './app-shell.component.scss'
})
export class AppShellComponent implements OnInit {
  private readonly data = inject(MockDataService);
  private readonly auth = inject(AuthService);
  private readonly orgService = inject(OrganizationService);
  private readonly router = inject(Router);
  private readonly notificationService = inject(NotificationService);

  readonly unreadNotifications = this.notificationService.unreadCount;
  readonly recentNotifications = this.notificationService.notifications;
  readonly showNotifications = signal(false);

  readonly navItems = NAV_ITEMS;
  readonly approvalsPending = this.data.approvals;

  readonly currentUser = this.auth.currentUser;
  readonly organizations = this.orgService.organizations;
  readonly activeOrgId = this.orgService.activeOrgId;
  readonly activeOrg = computed(
    () => this.organizations().find((o) => o.id === this.activeOrgId()) ?? null
  );
  readonly initials = computed(() => {
    const name = this.currentUser()?.full_name ?? '';
    return name
      .split(' ')
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join('')
      .toUpperCase();
  });

  readonly showUserMenu = signal(false);
  readonly showCreateOrg = signal(false);
  readonly newOrgName = signal('');

  ngOnInit(): void {
    if (!this.currentUser()) {
      this.auth.fetchCurrentUser().subscribe({ error: () => this.handleSessionExpired() });
    }
    if (this.organizations().length === 0) {
      this.orgService.listMine().subscribe({ error: () => this.handleSessionExpired() });
    }
    this.notificationService.refreshUnreadCount();
  }

  toggleNotifications(): void {
    const next = !this.showNotifications();
    this.showNotifications.set(next);
    if (next) {
      this.notificationService.list().subscribe();
    }
  }

  openNotification(id: string, linkUrl: string): void {
    this.notificationService.markRead(id).subscribe();
    this.showNotifications.set(false);
    if (linkUrl) {
      this.router.navigateByUrl(linkUrl);
    }
  }

  private handleSessionExpired(): void {
    this.auth.logout();
    this.router.navigateByUrl('/login');
  }

  setOrg(id: string) {
    this.orgService.setActiveOrg(id);
    this.router.navigateByUrl('/dashboard');
  }

  toggleUserMenu() {
    this.showUserMenu.update((v) => !v);
  }

  logout() {
    this.auth.logout();
    this.router.navigateByUrl('/login');
  }

  openCreateOrg() {
    this.showCreateOrg.set(true);
    this.newOrgName.set('');
  }

  closeCreateOrg() {
    this.showCreateOrg.set(false);
  }

  submitCreateOrg() {
    const name = this.newOrgName().trim();
    if (!name) return;
    this.orgService.create(name).subscribe(() => {
      this.showCreateOrg.set(false);
      this.router.navigateByUrl('/dashboard');
    });
  }
}
