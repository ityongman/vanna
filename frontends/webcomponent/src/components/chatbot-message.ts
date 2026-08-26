import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { chatbotDesignTokens } from '../styles/chatbot-design-tokens.js';

@customElement('chatbot-message')
export class ChatbotMessage extends LitElement {
  static styles = [
    chatbotDesignTokens,
    css`
      :host {
        display: block;
        padding: 0 var(--chatbot-space-2);
        margin-bottom: var(--chatbot-space-4);
        font-family: var(--chatbot-font-family-default);
        animation: fade-in-up 0.25s ease-out;
      }

      :host(:last-of-type) {
        margin-bottom: 0;
      }

      @keyframes fade-in-up {
        from {
          opacity: 0;
          transform: translateY(16px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .message {
        position: relative;
        padding: var(--chatbot-space-4) var(--chatbot-space-5);
        border-radius: var(--chatbot-chat-bubble-radius);
        word-wrap: break-word;
        line-height: 1.6;
        display: flex;
        flex-direction: column;
        gap: var(--chatbot-space-2);
        max-width: min(85%, 580px);
        transition: transform var(--chatbot-duration-200) ease, box-shadow var(--chatbot-duration-200) ease;
        backdrop-filter: blur(8px);
      }

      .message.assistant {
        background: var(--chatbot-background-root);
        border: 1px solid var(--chatbot-outline-dimmer);
        color: var(--chatbot-foreground-default);
        box-shadow: var(--chatbot-shadow-sm);
        border-radius: var(--chatbot-chat-bubble-radius) var(--chatbot-chat-bubble-radius) var(--chatbot-chat-bubble-radius) var(--chatbot-space-2);
      }

      .message.user {
        margin-left: auto;
        max-width: min(80%, 500px);
        background: linear-gradient(135deg, var(--chatbot-accent-primary-stronger) 0%, var(--chatbot-accent-primary-default) 100%);
        color: white;
        box-shadow: var(--chatbot-shadow-md);
        border-radius: var(--chatbot-chat-bubble-radius) var(--chatbot-chat-bubble-radius) var(--chatbot-space-2) var(--chatbot-chat-bubble-radius);
        border: 1px solid rgba(255, 255, 255, 0.2);
      }

      .message:hover {
        transform: translateY(-1px);
      }

      .message.assistant:hover {
        box-shadow: var(--chatbot-shadow-md);
        border-color: var(--chatbot-outline-hover);
      }

      .message.user:hover {
        box-shadow: var(--chatbot-shadow-lg);
      }

      .message-content {
        margin: 0;
        font-size: 15px;
        letter-spacing: 0.01em;
        white-space: pre-wrap;
        font-weight: 400;
      }

      .message-content a {
        color: inherit;
        font-weight: 500;
        text-decoration: underline;
        text-decoration-thickness: 1px;
        text-underline-offset: 2px;
        opacity: 0.9;
      }

      .message-content code {
        font-family: var(--chatbot-font-family-mono);
        background: var(--chatbot-background-higher);
        padding: 2px 6px;
        border-radius: var(--chatbot-border-radius-sm);
        font-size: 13px;
        border: 1px solid var(--chatbot-outline-dimmer);
      }

      .message.user .message-content code {
        background: rgba(255, 255, 255, 0.2);
        border-color: rgba(255, 255, 255, 0.3);
      }

      .message-timestamp {
        display: inline-flex;
        align-items: center;
        gap: var(--chatbot-space-1);
        font-size: 11px;
        letter-spacing: 0.05em;
        margin-top: var(--chatbot-space-2);
        font-family: var(--chatbot-font-family-default);
        opacity: 0.7;
        font-weight: 500;
      }

      .message-timestamp::before {
        content: '';
        width: 3px;
        height: 3px;
        border-radius: var(--chatbot-border-radius-full);
        background: currentColor;
        opacity: 0.8;
      }

      .message.assistant .message-timestamp {
        align-self: flex-start;
        color: var(--chatbot-foreground-dimmest);
      }

      .message.assistant .message-timestamp::before {
        background: var(--chatbot-accent-primary-default);
      }

      .message.user .message-timestamp {
        align-self: flex-end;
        color: rgba(255, 255, 255, 0.8);
      }

      .message.user .message-timestamp::before {
        background: rgba(255, 255, 255, 0.8);
      }

      :host([theme="dark"]) .message.assistant {
        background: var(--chatbot-background-higher);
        border: 1px solid var(--chatbot-outline-default);
        color: var(--chatbot-foreground-default);
        box-shadow: var(--chatbot-shadow-md);
      }

      :host([theme="dark"]) .message.assistant .message-content code {
        background: var(--chatbot-background-highest);
        border-color: var(--chatbot-outline-default);
      }

      :host([theme="dark"]) .message.assistant .message-timestamp {
        color: var(--chatbot-foreground-dimmest);
      }

      :host([theme="dark"]) .message.assistant .message-timestamp::before {
        background: var(--chatbot-accent-primary-default);
      }

      :host([theme="dark"]) .message.user {
        background: linear-gradient(135deg, var(--chatbot-accent-primary-stronger) 0%, var(--chatbot-accent-primary-default) 100%);
        color: white;
        box-shadow: var(--chatbot-shadow-lg);
      }

      :host([theme="dark"]) .message.user .message-content code {
        background: rgba(255, 255, 255, 0.15);
        border-color: rgba(255, 255, 255, 0.25);
      }

      :host([theme="dark"]) .message.user .message-timestamp {
        color: rgba(255, 255, 255, 0.8);
      }

      :host([theme="dark"]) .message.user .message-timestamp::before {
        background: rgba(255, 255, 255, 0.8);
      }

      @media (max-width: 600px) {
        .message {
          max-width: 100%;
        }

        .message.user {
          max-width: 100%;
        }
      }
    `
  ];

  @property() content = '';
  @property() type: 'user' | 'assistant' = 'user';
  @property({ type: Number }) timestamp = Date.now();
  @property({ reflect: true }) theme = 'light';

  private formatTimestamp(timestamp: number): string {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  render() {
    return html`
      <div class="message ${this.type}">
        <div class="message-content">${this.content}</div>
        <div class="message-timestamp">
          ${this.formatTimestamp(this.timestamp)}
        </div>
      </div>
    `;
  }
}
