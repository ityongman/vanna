import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { chatbotDesignTokens } from '../styles/chatbot-design-tokens.js';

export interface TaskItem {
  id: string;
  title: string;
  description?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress?: number;
  timestamp?: string;
}

@customElement('rich-task-list')
export class RichTaskList extends LitElement {
  static styles = [
    chatbotDesignTokens,
    css`
      :host {
        display: block;
        margin-bottom: var(--chatbot-space-4);
        font-family: var(--chatbot-font-family-default);
      }

      .task-list {
        border: 1px solid var(--chatbot-outline-default);
        border-radius: var(--chatbot-border-radius-lg);
        background: var(--chatbot-background-default);
        box-shadow: var(--chatbot-shadow-sm);
        overflow: hidden;
        transition: box-shadow var(--chatbot-duration-200) ease;
      }

      .task-list:hover {
        box-shadow: var(--chatbot-shadow-md);
      }

      .task-list-header {
        padding: var(--chatbot-space-4) var(--chatbot-space-5);
        background: var(--chatbot-background-higher);
        border-bottom: 1px solid var(--chatbot-outline-default);
      }

      .task-list-title {
        margin: 0 0 var(--chatbot-space-3) 0;
        font-size: 1rem;
        font-weight: 600;
        color: var(--chatbot-foreground-default);
      }

      .task-list-progress {
        display: flex;
        align-items: center;
        gap: var(--chatbot-space-3);
      }

      .progress-text {
        font-size: 0.875rem;
        color: var(--chatbot-foreground-dimmer);
        min-width: fit-content;
      }

      .progress-bar {
        flex: 1;
        height: 6px;
        background: var(--chatbot-background-root);
        border-radius: 3px;
        overflow: hidden;
      }

      .progress-fill {
        height: 100%;
        background: var(--chatbot-accent-primary-default);
        border-radius: 3px;
        transition: width var(--chatbot-duration-300) ease;
      }

      .progress-fill.animated {
        animation: progressPulse 2s ease-in-out infinite;
      }

      @keyframes progressPulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
      }

      .progress-fill.status-success {
        background: var(--chatbot-accent-positive-default);
      }

      .progress-fill.status-warning {
        background: var(--chatbot-accent-warning-default);
      }

      .progress-fill.status-error {
        background: var(--chatbot-accent-negative-default);
      }

      .task-list-items {
        padding: var(--chatbot-space-2);
      }

      .task-item {
        display: flex;
        align-items: flex-start;
        gap: var(--chatbot-space-3);
        padding: var(--chatbot-space-3);
        border-radius: var(--chatbot-border-radius-md);
        transition: background-color var(--chatbot-duration-200) ease;
      }

      .task-item:hover {
        background: var(--chatbot-background-root);
      }

      .task-item.status-completed {
        opacity: 0.7;
      }

      .task-item.status-failed {
        background: rgba(239, 68, 68, 0.1);
      }

      .task-icon {
        font-size: 1rem;
        margin-top: 0.125rem;
      }

      .task-content {
        flex: 1;
        min-width: 0;
      }

      .task-title {
        font-weight: 500;
        color: var(--chatbot-foreground-default);
        margin-bottom: var(--chatbot-space-1);
      }

      .task-description {
        font-size: 0.875rem;
        color: var(--chatbot-foreground-dimmer);
        margin-bottom: var(--chatbot-space-2);
      }

      .task-progress {
        display: flex;
        align-items: center;
        gap: var(--chatbot-space-2);
        margin-bottom: var(--chatbot-space-2);
      }

      .task-progress-bar {
        flex: 1;
        height: 4px;
        background: var(--chatbot-background-root);
        border-radius: 2px;
        overflow: hidden;
      }

      .task-progress-fill {
        height: 100%;
        background: var(--chatbot-accent-primary-default);
        border-radius: 2px;
        transition: width var(--chatbot-duration-300) ease;
      }

      .task-progress-text {
        font-size: 0.75rem;
        color: var(--chatbot-foreground-dimmer);
        min-width: fit-content;
      }

      .task-timestamp {
        font-size: 0.75rem;
        color: var(--chatbot-foreground-dimmest);
      }

      /* Responsive adjustments */
      @media (max-width: 768px) {
        .task-list-header {
          padding-left: var(--chatbot-space-4);
          padding-right: var(--chatbot-space-4);
        }

        .task-list-progress {
          flex-direction: column;
          align-items: stretch;
          gap: var(--chatbot-space-2);
        }
      }
    `
  ];

  @property() title = '';
  @property({ type: Array }) tasks: TaskItem[] = [];
  @property({ type: Boolean }) showProgress = true;
  @property({ type: Boolean }) showTimestamps = false;
  @property() theme: 'light' | 'dark' = 'dark';

  private get completedTasks(): number {
    return this.tasks.filter(task => task.status === 'completed').length;
  }

  private get progressPercentage(): number {
    return this.tasks.length > 0 ? (this.completedTasks / this.tasks.length) * 100 : 0;
  }

  private getStatusIcon(status: string): string {
    const icons = {
      'pending': '⏳',
      'running': '🔄',
      'completed': '✅',
      'failed': '❌'
    };
    return icons[status as keyof typeof icons] || '⏳';
  }

  private renderTask(task: TaskItem) {
    const statusIcon = this.getStatusIcon(task.status);

    return html`
      <div class="task-item status-${task.status}" data-task-id="${task.id}">
        <div class="task-icon">${statusIcon}</div>
        <div class="task-content">
          <div class="task-title">${task.title}</div>
          ${task.description ? html`
            <div class="task-description">${task.description}</div>
          ` : ''}
          ${task.progress !== null && task.progress !== undefined ? html`
            <div class="task-progress">
              <div class="task-progress-bar">
                <div class="task-progress-fill" style="width: ${task.progress * 100}%"></div>
              </div>
              <span class="task-progress-text">${Math.round(task.progress * 100)}%</span>
            </div>
          ` : ''}
          ${this.showTimestamps && task.timestamp ? html`
            <div class="task-timestamp">${task.timestamp}</div>
          ` : ''}
        </div>
      </div>
    `;
  }

  render() {
    return html`
      <div class="task-list">
        <div class="task-list-header">
          <h3 class="task-list-title">${this.title}</h3>
          ${this.showProgress ? html`
            <div class="task-list-progress">
              <span class="progress-text">${this.completedTasks}/${this.tasks.length} completed</span>
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${this.progressPercentage}%"></div>
              </div>
            </div>
          ` : ''}
        </div>
        <div class="task-list-items">
          ${this.tasks.map(task => this.renderTask(task))}
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'rich-task-list': RichTaskList;
  }
}