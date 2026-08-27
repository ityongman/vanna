// Build metadata: injected by vite define at build time.
// In dev mode the constants are not replaced, so fall back gracefully
// (referencing an undefined global would throw ReferenceError and break
// the whole module, killing all web components).
const buildVersion =
  typeof __BUILD_VERSION__ !== 'undefined' ? __BUILD_VERSION__ : 'dev';
const buildTime =
  typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : new Date().toISOString();

// Log build information when the module loads
console.log(
  '%c🎨 Chatbot Web Components',
  'color: #4CAF50; font-weight: bold; font-size: 14px;'
);
console.log(`%c📦 Version: ${buildVersion}`, 'color: #2196F3; font-weight: bold;');
console.log(`%c🕐 Built: ${buildTime}`, 'color: #FF9800; font-weight: bold;');
console.log(
  '%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━',
  'color: #9E9E9E;'
);

export { ChatbotChat } from './components/chatbot-chat';
export { ChatbotMessage } from './components/chatbot-message';
export { ChatbotStatusBar } from './components/chatbot-status-bar';
export { ChatbotProgressTracker } from './components/chatbot-progress-tracker';
export { PlotlyChart } from './components/plotly-chart';

// Rich component system
export {
  ComponentRegistry,
  ComponentManager,
  CardComponentRenderer,
  TaskListComponentRenderer,
  ProgressBarComponentRenderer,
  NotificationComponentRenderer,
  StatusIndicatorComponentRenderer,
  TextComponentRenderer
} from './components/rich-component-system';

// Rich component styles are injected automatically by the ComponentManager
