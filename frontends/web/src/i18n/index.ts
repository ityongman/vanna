/**
 * Simple i18n implementation.
 * TODO: replace with @m5/i18n when the package is available.
 */

import zhCN from './locales/zh-CN';
import zhTW from './locales/zh-TW';
import enUS from './locales/en-US';

export type Language = 'zh-CN' | 'zh-TW' | 'en-US';
export type Namespace = 'route' | 'menu' | 'common';

const localeMap: Record<Language, Record<Namespace, Record<string, string>>> = {
  'zh-CN': zhCN,
  'zh-TW': zhTW,
  'en-US': enUS,
};

let currentLanguage: Language = 'zh-CN';

export function setLanguage(lang: Language) {
  currentLanguage = lang;
}

export function getLanguage(): Language {
  return currentLanguage;
}

/**
 * Get a translated string by namespace and key.
 * @param ns - namespace (route, menu, common)
 * @param key - dot-separated key, e.g. 'chat.title'
 * @param fallback - fallback string if key not found
 */
export function t(ns: Namespace, key: string, fallback?: string): string {
  const container = localeMap[currentLanguage]?.[ns];
  const value = container?.[key];
  return value ?? fallback ?? key;
}

/**
 * Get the entire namespace container for the current language.
 * Used for menuDataRender where you need the full map.
 */
export function getNamespace(ns: Namespace): Record<string, string> {
  return localeMap[currentLanguage]?.[ns] ?? {};
}

/**
 * Get Ant Design locale object based on current language.
 */
export function getAntdLocale() {
  // This will be dynamically imported in App.tsx
  return currentLanguage;
}
