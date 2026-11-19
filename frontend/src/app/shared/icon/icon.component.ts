import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { toSignal } from '@angular/core/rxjs-interop';
import { IconService } from './icon.service';
import { switchMap, of } from 'rxjs';
import { toObservable } from '@angular/core/rxjs-interop';

@Component({
  selector: 'sf-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="sf-icon" [innerHTML]="svg()"></span>`,
  styles: [
    `
      :host {
        display: inline-flex;
        line-height: 0;
      }
      span {
        display: inline-flex;
      }
      ::ng-deep svg {
        width: 100%;
        height: 100%;
      }
    `
  ]
})
export class IconComponent {
  private readonly iconService = inject(IconService);
  private readonly sanitizer = inject(DomSanitizer);

  /** e.g. 'navigation/dashboard', 'status/success', 'agents/coding-agent' */
  name = input.required<string>();

  private readonly raw = toSignal(
    toObservable(this.name).pipe(switchMap((n) => (n ? this.iconService.load(n) : of('')))),
    { initialValue: '' }
  );

  svg() {
    return this.sanitizer.bypassSecurityTrustHtml(this.raw());
  }
}
