import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../mock-data.service';
import { NAV_ITEMS } from '../nav-items';

@Component({
  selector: 'sf-app-shell',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app-shell.component.html',
  styleUrl: './app-shell.component.scss'
})
export class AppShellComponent {
  private readonly data = inject(MockDataService);

  readonly navItems = NAV_ITEMS;
  readonly user = this.data.currentUser;
  readonly organizations = this.data.organizations;
  readonly activeOrg = this.data.activeOrganization;
  readonly approvalsPending = this.data.approvals;

  setOrg(id: string) {
    const org = this.organizations().find((o) => o.id === id);
    if (org) this.activeOrg.set(org);
  }
}
