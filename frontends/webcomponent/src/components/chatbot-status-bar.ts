import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { chatbotDesignTokens } from '../styles/chatbot-design-tokens.js';

@customElement('chatbot-status-bar')
export class ChatbotStatusBar extends LitElement {
  static styles = [
    chatbotDesignTokens,
    css`
      :host {
        display: block;
        background: rgba(254, 93, 38, 0.1);
        border: 2px solid var(--chatbot-orange);
        border-radius: var(--chatbot-border-radius-xl);
        padding: var(--chatbot-space-4) var(--chatbot-space-5);
        margin-bottom: var(--chatbot-space-4);
        font-family: var(--chatbot-font-family-default);
        font-size: 14px;
        font-weight: 500;
        color: var(--chatbot-navy);
        backdrop-filter: blur(12px);
        box-shadow:
          var(--chatbot-shadow-lg),
          0 0 0 1px rgba(254, 93, 38, 0.1);
        
        /* Animation properties */
        opacity: 1;
        transform: translateY(0) scale(1);
        max-height: 200px;
        overflow: hidden;
        transition: 
          opacity var(--chatbot-duration-300) cubic-bezier(0.4, 0, 0.2, 1),
          transform var(--chatbot-duration-300) cubic-bezier(0.4, 0, 0.2, 1),
          max-height var(--chatbot-duration-300) ease,
          margin var(--chatbot-duration-300) ease,
          padding var(--chatbot-duration-300) ease,
          box-shadow var(--chatbot-duration-200) ease;
      }

      /* Hide when there's no actual content */
      :host(.no-content) {
        opacity: 0;
        transform: translateY(-8px) scale(0.95);
        max-height: 0;
        margin: 0;
        padding: 0;
        pointer-events: none;
      }

      :host(:empty) {
        display: none;
      }

      /* Entrance animation when content appears */
      :host(.entering) {
        animation: statusEnter var(--chatbot-duration-300) ease-out;
      }

      /* Exit animation when content disappears */
      :host(.exiting) {
        animation: statusExit var(--chatbot-duration-300) ease-in;
      }

      @keyframes statusEnter {
        0% {
          opacity: 0;
          transform: translateY(-12px) scale(0.9);
          max-height: 0;
        }
        50% {
          opacity: 0.8;
          transform: translateY(-2px) scale(1.02);
        }
        100% {
          opacity: 1;
          transform: translateY(0) scale(1);
          max-height: 200px;
        }
      }

      @keyframes statusExit {
        0% {
          opacity: 1;
          transform: translateY(0) scale(1);
          max-height: 200px;
        }
        50% {
          opacity: 0.5;
          transform: translateY(-4px) scale(0.98);
        }
        100% {
          opacity: 0;
          transform: translateY(-12px) scale(0.9);
          max-height: 0;
        }
      }

      :host([status="working"]) {
        background: var(--chatbot-orange);
        border-color: var(--chatbot-orange);
        color: white;
        box-shadow:
          var(--chatbot-shadow-xl),
          0 0 0 2px rgba(254, 93, 38, 0.3),
          0 0 20px rgba(254, 93, 38, 0.4);
      }

      :host([status="error"]) {
        background: linear-gradient(135deg, var(--chatbot-accent-negative-subtle) 0%, rgba(239, 68, 68, 0.15) 100%);
        border-color: var(--chatbot-accent-negative-default);
        color: var(--chatbot-accent-negative-stronger);
        box-shadow: 
          var(--chatbot-shadow-xl),
          0 0 0 2px rgba(239, 68, 68, 0.3),
          0 0 20px rgba(239, 68, 68, 0.2);
        animation: errorShake 0.5s ease-in-out, errorGlow 2s ease-in-out;
      }

      :host([status="success"]) {
        background: linear-gradient(135deg, var(--chatbot-accent-positive-subtle) 0%, rgba(16, 185, 129, 0.15) 100%);
        border-color: var(--chatbot-accent-positive-default);
        color: var(--chatbot-accent-positive-stronger);
        box-shadow: 
          var(--chatbot-shadow-xl),
          0 0 0 2px rgba(16, 185, 129, 0.3),
          0 0 20px rgba(16, 185, 129, 0.2);
        animation: successPulse 0.6s ease-out, successGlow 2s ease-out;
      }

      @keyframes errorShake {
        0%, 100% { transform: translateX(0); }
        10%, 30%, 50%, 70%, 90% { transform: translateX(-4px); }
        20%, 40%, 60%, 80% { transform: translateX(4px); }
      }

      @keyframes successPulse {
        0% { 
          transform: scale(1); 
        }
        50% { 
          transform: scale(1.05); 
        }
        100% { 
          transform: scale(1); 
        }
      }

      .status-content {
        display: flex;
        align-items: center;
        gap: var(--chatbot-space-3);
        animation: contentFadeIn var(--chatbot-duration-200) ease-out;
      }

      @keyframes contentFadeIn {
        0% {
          opacity: 0;
          transform: translateY(4px);
        }
        100% {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .status-indicator {
        width: 12px;
        height: 12px;
        border-radius: var(--chatbot-border-radius-full);
        background: var(--chatbot-accent-primary-default);
        flex-shrink: 0;
        box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.5), 0 2px 8px rgba(0, 0, 0, 0.15);
      }

      .status-indicator.working {
        background: white;
        animation: workingPulse 1.5s ease-in-out infinite;
      }

      .status-indicator.error {
        background: linear-gradient(45deg, var(--chatbot-accent-negative-default), var(--chatbot-accent-negative-stronger));
        box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.5), 0 0 8px rgba(239, 68, 68, 0.4);
      }

      .status-indicator.success {
        background: linear-gradient(45deg, var(--chatbot-accent-positive-default), var(--chatbot-accent-positive-stronger));
        box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.5), 0 0 8px rgba(16, 185, 129, 0.4);
      }

      .spinner {
        width: 16px;
        height: 16px;
        border: 3px solid rgba(21, 168, 168, 0.3);
        border-top-color: var(--chatbot-teal);
        border-radius: var(--chatbot-border-radius-full);
        animation: spin 1s linear infinite, spinnerGlow 2s ease-in-out infinite;
        flex-shrink: 0;
      }

      .status-text {
        flex: 1;
        font-weight: 600;
        line-height: 1.4;
        letter-spacing: 0.01em;
      }

      .status-detail {
        font-size: 12px;
        color: var(--chatbot-foreground-dimmest);
        margin-left: var(--chatbot-space-4);
        opacity: 0.9;
        font-weight: 500;
      }

      .status-actions {
        display: flex;
        align-items: center;
        gap: var(--chatbot-space-2);
        margin-left: auto;
      }

      .status-button {
        padding: var(--chatbot-space-1) var(--chatbot-space-2);
        border: 1px solid var(--chatbot-outline-default);
        border-radius: var(--chatbot-border-radius-sm);
        background: var(--chatbot-background-subtle);
        color: var(--chatbot-foreground-dimmer);
        font-size: 11px;
        font-weight: 500;
        cursor: pointer;
        transition: all var(--chatbot-duration-150) ease;
      }

      .status-button:hover {
        background: var(--chatbot-background-higher);
        border-color: var(--chatbot-outline-hover);
        color: var(--chatbot-foreground-default);
      }

      @keyframes spin {
        to {
          transform: rotate(360deg);
        }
      }

      @keyframes pulse {
        0%, 100% {
          opacity: 1;
          transform: scale(1);
        }
        50% {
          opacity: 0.6;
          transform: scale(1.1);
        }
      }

      @keyframes workingPulse {
        0%, 100% {
          opacity: 1;
          transform: scale(1);
          box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.8), 0 2px 8px rgba(255, 255, 255, 0.3);
        }
        50% {
          opacity: 0.9;
          transform: scale(1.2);
          box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.9), 0 4px 12px rgba(255, 255, 255, 0.5);
        }
      }

      @keyframes spinnerGlow {
        0%, 100% {
          filter: drop-shadow(0 0 2px rgba(21, 168, 168, 0.5));
        }
        50% {
          filter: drop-shadow(0 0 6px rgba(21, 168, 168, 0.8));
        }
      }

      @keyframes errorGlow {
        0% {
          box-shadow: 
            var(--chatbot-shadow-xl),
            0 0 0 2px rgba(239, 68, 68, 0.3),
            0 0 20px rgba(239, 68, 68, 0.2);
        }
        50% {
          box-shadow: 
            var(--chatbot-shadow-2xl),
            0 0 0 3px rgba(239, 68, 68, 0.4),
            0 0 30px rgba(239, 68, 68, 0.3);
        }
        100% {
          box-shadow: 
            var(--chatbot-shadow-xl),
            0 0 0 2px rgba(239, 68, 68, 0.3),
            0 0 20px rgba(239, 68, 68, 0.2);
        }
      }

      @keyframes successGlow {
        0% {
          box-shadow: 
            var(--chatbot-shadow-xl),
            0 0 0 2px rgba(16, 185, 129, 0.3),
            0 0 20px rgba(16, 185, 129, 0.2);
        }
        50% {
          box-shadow: 
            var(--chatbot-shadow-2xl),
            0 0 0 3px rgba(16, 185, 129, 0.4),
            0 0 30px rgba(16, 185, 129, 0.3);
        }
        100% {
          box-shadow: 
            var(--chatbot-shadow-xl),
            0 0 0 2px rgba(16, 185, 129, 0.3),
            0 0 20px rgba(16, 185, 129, 0.2);
        }
      }

      /* Dark theme overrides */
      :host([theme="dark"]) {
        background: var(--chatbot-background-higher);
        border-color: var(--chatbot-outline-default);
      }

      :host([theme="dark"]) .status-button {
        background: var(--chatbot-background-highest);
        border-color: var(--chatbot-outline-default);
      }

      :host([theme="dark"]) .status-button:hover {
        background: var(--chatbot-background-highest);
        border-color: var(--chatbot-outline-hover);
      }
    `
  ];

  @property() status: 'idle' | 'working' | 'error' | 'success' = 'idle';
  @property() message = '';
  @property() detail = '';
  @property() theme = 'light';

  private _previousHasContent = false;
  private _enterTimeout: number | null = null;
  private _exitTimeout: number | null = null;
  private _lastUpdateTime = 0;

  disconnectedCallback() {
    super.disconnectedCallback();

    // Clean up pending animation timeouts when component is removed
    if (this._enterTimeout !== null) {
      clearTimeout(this._enterTimeout);
      this._enterTimeout = null;
    }
    if (this._exitTimeout !== null) {
      clearTimeout(this._exitTimeout);
      this._exitTimeout = null;
    }
  }

  updated(_changedProperties: Map<string | number | symbol, unknown>) {
    // Update CSS class based on content
    const hasContent = Boolean(this.message && this.message.trim());

    // Cancel any pending animation timeouts to prevent race conditions
    if (this._enterTimeout !== null) {
      clearTimeout(this._enterTimeout);
      this._enterTimeout = null;
    }
    if (this._exitTimeout !== null) {
      clearTimeout(this._exitTimeout);
      this._exitTimeout = null;
    }

    // Debounce rapid updates to prevent animation jank
    const now = Date.now();
    const timeSinceLastUpdate = now - this._lastUpdateTime;
    const shouldDebounce = timeSinceLastUpdate < 100; // 100ms debounce

    // Handle animation classes
    if (hasContent !== this._previousHasContent) {
      if (hasContent) {
        // Content appeared - animate in
        this.classList.remove('no-content', 'exiting');

        if (!shouldDebounce) {
          // Only animate if not rapid-firing
          this.classList.add('entering');

          // Remove entering class after animation
          this._enterTimeout = window.setTimeout(() => {
            this.classList.remove('entering');
            this._enterTimeout = null;
          }, 300);
        }
      } else {
        // Content disappeared - animate out
        this.classList.remove('entering');

        if (!shouldDebounce) {
          // Only animate if not rapid-firing
          this.classList.add('exiting');

          // Add no-content class after animation
          this._exitTimeout = window.setTimeout(() => {
            this.classList.remove('exiting');
            this.classList.add('no-content');
            this._exitTimeout = null;
          }, 300);
        } else {
          // If rapid-firing, skip animation and go straight to no-content
          this.classList.add('no-content');
        }
      }
    } else if (!hasContent) {
      // Ensure no-content class is applied when no content
      this.classList.add('no-content');
    }

    this._previousHasContent = hasContent;
    this._lastUpdateTime = now;
  }

  render() {
    // Only show if there's actual content (message) to display
    if (!this.message || !this.message.trim()) {
      return html``;
    }

    return html`
      <div class="status-content">
        ${this.status === 'working'
          ? html`<div class="spinner"></div>`
          : html`<div class="status-indicator ${this.status}"></div>`
        }
        <span class="status-text">${this.message}</span>
        ${this.detail ? html`<span class="status-detail">${this.detail}</span>` : ''}
      </div>
    `;
  }
}