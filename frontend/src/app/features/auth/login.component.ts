import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { catchError, of, switchMap } from 'rxjs';
import { IconComponent } from '../../shared/icon/icon.component';
import { AuthService } from '../../core/auth/auth.service';
import { OrganizationService } from '../../core/org/organization.service';

type Mode = 'signin' | 'register';

@Component({
  selector: 'sf-login',
  standalone: true,
  imports: [FormsModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss'
})
export class LoginComponent {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly orgs = inject(OrganizationService);

  readonly mode = signal<Mode>('signin');
  readonly isRegister = computed(() => this.mode() === 'register');

  email = signal('');
  password = signal('');
  fullName = signal('');
  showPassword = signal(false);
  submitting = signal(false);
  errorMessage = signal('');

  readonly title = computed(() => (this.isRegister() ? 'Create your workspace' : 'Welcome back'));
  readonly subtitle = computed(() =>
    this.isRegister()
      ? 'Set up your Software Factory account'
      : 'Sign in to your Software Factory workspace'
  );
  readonly submitLabel = computed(() => {
    if (this.submitting()) return this.isRegister() ? 'Creating account…' : 'Signing in…';
    return this.isRegister() ? 'Create account' : 'Sign in';
  });

  togglePassword() {
    this.showPassword.update((v) => !v);
  }

  toggleMode() {
    this.mode.update((m) => (m === 'signin' ? 'register' : 'signin'));
    this.errorMessage.set('');
  }

  submit() {
    if (!this.email() || !this.password() || (this.isRegister() && !this.fullName())) return;
    this.submitting.set(true);
    this.errorMessage.set('');

    const afterAuth = () => {
      this.auth
        .fetchCurrentUser()
        .pipe(switchMap(() => this.orgs.listMine()))
        .subscribe({
          next: () => {
            this.submitting.set(false);
            this.router.navigateByUrl('/dashboard');
          },
          error: () => {
            this.submitting.set(false);
            this.router.navigateByUrl('/dashboard');
          }
        });
    };

    if (this.isRegister()) {
      this.auth
        .register(this.email(), this.password(), this.fullName())
        .pipe(
          switchMap(() => this.auth.login(this.email(), this.password())),
          catchError((err: HttpErrorResponse) => {
            this.submitting.set(false);
            this.errorMessage.set(this.describeError(err));
            return of(null);
          })
        )
        .subscribe((tokens) => {
          if (tokens) afterAuth();
        });
    } else {
      this.auth
        .login(this.email(), this.password())
        .pipe(
          catchError((err: HttpErrorResponse) => {
            this.submitting.set(false);
            this.errorMessage.set(this.describeError(err));
            return of(null);
          })
        )
        .subscribe((tokens) => {
          if (tokens) afterAuth();
        });
    }
  }

  private describeError(err: HttpErrorResponse): string {
    if (err.status === 0) {
      return 'Cannot reach the Software Factory API. Is the backend running?';
    }
    const detail = (err.error as { detail?: string } | null)?.detail;
    return detail ?? 'Something went wrong. Please try again.';
  }
}
