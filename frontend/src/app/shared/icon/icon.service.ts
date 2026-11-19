import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, shareReplay, map } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class IconService {
  private readonly http = inject(HttpClient);
  private readonly cache = new Map<string, Observable<string>>();

  /**
   * name is a path without extension, relative to assets/icons unless it
   * starts with 'logos/', in which case it's relative to assets/ directly
   * (e.g. 'navigation/dashboard' -> assets/icons/navigation/dashboard.svg,
   * 'logos/software-factory-mark' -> assets/logos/software-factory-mark.svg).
   */
  load(name: string): Observable<string> {
    let obs = this.cache.get(name);
    if (!obs) {
      const path = name.startsWith('logos/') ? `assets/${name}.svg` : `assets/icons/${name}.svg`;
      obs = this.http.get(path, { responseType: 'text' }).pipe(
        map((raw) => raw.replace(/stroke="#[0-9a-fA-F]{3,6}"/g, 'stroke="currentColor"')),
        shareReplay(1)
      );
      this.cache.set(name, obs);
    }
    return obs;
  }
}
