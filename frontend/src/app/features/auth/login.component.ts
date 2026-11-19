import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';

@Component({
  selector: 'sf-login',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss'
})
export class LoginComponent {
  private readonly router = inject(Router);

  email = signal('');
  password = signal('');
  showPassword = signal(false);
  submitting = signal(false);

  togglePassword() {
    this.showPassword.update((v) => !v);
  }

  submit() {
    if (!this.email() || !this.password()) return;
    this.submitting.set(true);
    // No real identity provider is wired up in this UI-shell pass.
    // Navigation proves the route/guard-free flow works end to end.
    setTimeout(() => {
      this.submitting.set(false);
      this.router.navigateByUrl('/dashboard');
    }, 400);
  }
}
