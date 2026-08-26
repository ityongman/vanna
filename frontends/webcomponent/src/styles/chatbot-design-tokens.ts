import { css } from 'lit';

// Chatbot design tokens
export const chatbotDesignTokens = css`
  :host {
    /* Brand Colors */
    --chatbot-navy: rgb(2, 61, 96);
    --chatbot-cream: rgb(231, 225, 207);
    --chatbot-teal: rgb(21, 168, 168);
    --chatbot-orange: rgb(254, 93, 38);
    --chatbot-magenta: rgb(191, 19, 99);

    /* Color Palette - Light mode (default) */
    --chatbot-background-root: rgb(255, 255, 255);
    --chatbot-background-default: rgb(231, 225, 207);
    --chatbot-background-higher: rgb(244, 246, 248);
    --chatbot-background-highest: rgb(229, 231, 235);
    --chatbot-background-subtle: rgb(248, 250, 252);
    --chatbot-background-lower: rgb(239, 242, 245);

    --chatbot-foreground-default: rgb(2, 61, 96);
    --chatbot-foreground-dimmer: rgb(71, 85, 105);
    --chatbot-foreground-dimmest: rgb(100, 116, 139);

    --chatbot-accent-primary-default: rgb(21, 168, 168);
    --chatbot-accent-primary-stronger: rgb(2, 61, 96);
    --chatbot-accent-primary-strongest: rgb(2, 61, 96);
    --chatbot-accent-primary-subtle: rgba(21, 168, 168, 0.1);
    --chatbot-accent-primary-hover: rgb(21, 168, 168);

    --chatbot-accent-positive-default: rgb(21, 168, 168);
    --chatbot-accent-positive-stronger: rgb(2, 61, 96);
    --chatbot-accent-positive-subtle: rgba(21, 168, 168, 0.1);

    --chatbot-accent-negative-default: rgb(239, 68, 68);
    --chatbot-accent-negative-stronger: rgb(220, 38, 38);
    --chatbot-accent-negative-subtle: rgba(239, 68, 68, 0.1);

    --chatbot-accent-warning-default: rgb(254, 93, 38);
    --chatbot-accent-warning-stronger: rgb(254, 93, 38);
    --chatbot-accent-warning-subtle: rgba(254, 93, 38, 0.1);

    /* Outline/Border colors */
    --chatbot-outline-default: rgba(21, 168, 168, 0.3);
    --chatbot-outline-dimmer: rgb(241, 245, 249);
    --chatbot-outline-dimmest: rgb(248, 250, 252);
    --chatbot-outline-hover: rgb(21, 168, 168);

    /* Typography */
    --chatbot-font-family-default: "Space Grotesk", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
    --chatbot-font-family-serif: "Roboto Slab", ui-serif, Georgia, serif;
    --chatbot-font-family-mono: "Space Mono", ui-monospace, SFMono-Regular, "SF Mono", Monaco, Inconsolata, "Roboto Mono", "Ubuntu Mono", monospace;

    /* Spacing scale */
    --chatbot-space-0: 0px;
    --chatbot-space-1: 4px;
    --chatbot-space-2: 8px;
    --chatbot-space-3: 12px;
    --chatbot-space-4: 16px;
    --chatbot-space-5: 20px;
    --chatbot-space-6: 24px;
    --chatbot-space-7: 28px;
    --chatbot-space-8: 32px;
    --chatbot-space-10: 40px;
    --chatbot-space-12: 48px;
    --chatbot-space-16: 64px;

    /* Border radius */
    --chatbot-border-radius-sm: 6px;
    --chatbot-border-radius-md: 10px;
    --chatbot-border-radius-lg: 14px;
    --chatbot-border-radius-xl: 20px;
    --chatbot-border-radius-2xl: 24px;
    --chatbot-border-radius-full: 9999px;

    /* Shadows - Preline-inspired */
    --chatbot-shadow-xs: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    --chatbot-shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1);
    --chatbot-shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
    --chatbot-shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);
    --chatbot-shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    --chatbot-shadow-2xl: 0 25px 50px -12px rgba(0, 0, 0, 0.25);

    /* Animation durations */
    --chatbot-duration-75: 75ms;
    --chatbot-duration-100: 100ms;
    --chatbot-duration-150: 150ms;
    --chatbot-duration-200: 200ms;
    --chatbot-duration-300: 300ms;
    --chatbot-duration-500: 500ms;
    --chatbot-duration-700: 700ms;

    /* Z-index scale */
    --chatbot-z-dropdown: 1000;
    --chatbot-z-sticky: 1020;
    --chatbot-z-fixed: 1030;
    --chatbot-z-modal: 1040;
    --chatbot-z-popover: 1050;
    --chatbot-z-tooltip: 1060;

    /* Chat-specific tokens */
    --chatbot-chat-bubble-radius: 18px;
    --chatbot-chat-bubble-radius-sm: 12px;
    --chatbot-chat-spacing: 16px;
    --chatbot-chat-avatar-size: 40px;
  }

  /* Dark theme overrides */
  :host([theme="dark"]) {
    --chatbot-background-root: rgb(9, 11, 17);
    --chatbot-background-default: rgb(15, 18, 25);
    --chatbot-background-higher: rgb(24, 29, 39);
    --chatbot-background-highest: rgb(31, 39, 51);
    --chatbot-background-subtle: rgb(17, 21, 28);
    --chatbot-background-lower: rgb(6, 8, 12);

    --chatbot-foreground-default: rgb(248, 250, 252);
    --chatbot-foreground-dimmer: rgb(203, 213, 225);
    --chatbot-foreground-dimmest: rgb(148, 163, 184);

    --chatbot-accent-primary-default: rgb(21, 168, 168);
    --chatbot-accent-primary-stronger: rgb(21, 168, 168);
    --chatbot-accent-primary-strongest: rgb(2, 61, 96);
    --chatbot-accent-primary-subtle: rgba(21, 168, 168, 0.15);
    --chatbot-accent-primary-hover: rgb(21, 168, 168);

    --chatbot-accent-positive-default: rgb(21, 168, 168);
    --chatbot-accent-positive-stronger: rgb(21, 168, 168);
    --chatbot-accent-positive-subtle: rgba(21, 168, 168, 0.15);

    --chatbot-accent-negative-default: rgb(248, 113, 113);
    --chatbot-accent-negative-stronger: rgb(239, 68, 68);
    --chatbot-accent-negative-subtle: rgba(248, 113, 113, 0.15);

    --chatbot-accent-warning-default: rgb(254, 93, 38);
    --chatbot-accent-warning-stronger: rgb(254, 93, 38);
    --chatbot-accent-warning-subtle: rgba(254, 93, 38, 0.15);

    --chatbot-outline-default: rgba(21, 168, 168, 0.3);
    --chatbot-outline-dimmer: rgb(31, 41, 55);
    --chatbot-outline-dimmest: rgb(17, 24, 39);
    --chatbot-outline-hover: rgb(21, 168, 168);

    --chatbot-shadow-xs: 0 1px 2px 0 rgba(0, 0, 0, 0.6);
    --chatbot-shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.5), 0 1px 2px -1px rgba(0, 0, 0, 0.5);
    --chatbot-shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.4), 0 2px 4px -2px rgba(0, 0, 0, 0.4);
    --chatbot-shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.4), 0 4px 6px -4px rgba(0, 0, 0, 0.4);
    --chatbot-shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
    --chatbot-shadow-2xl: 0 25px 50px -12px rgba(0, 0, 0, 0.6);
  }
`;
