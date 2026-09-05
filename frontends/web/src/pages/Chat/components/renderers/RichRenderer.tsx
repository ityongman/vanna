import type { RichComponent } from '../../types';
import MarkdownText from './MarkdownText';
import DataFrameTable from './DataFrameTable';
import ChartView from './ChartView';
import CardView from './CardView';
import ActionButtons from './ActionButtons';
import StatusCardView from './StatusCardView';
import UnknownComponent from './UnknownComponent';

export interface RichRendererProps {
  component: RichComponent;
  onSendAction?: (action: string) => void;
}

/** UI-state-only components: applied live, invisible during history replay. */
const IGNORED_TYPES = new Set([
  'status_bar_update',
  'task_tracker_update',
  'chat_input_update',
]);

export default function RichRenderer({ component, onSendAction }: RichRendererProps) {
  if (component.visible === false) return null;
  if (IGNORED_TYPES.has(component.type)) return null;

  switch (component.type) {
    case 'text':
      return <MarkdownText component={component} />;
    case 'dataframe':
      return <DataFrameTable component={component} />;
    case 'chart':
      return <ChartView component={component} />;
    case 'card':
      return <CardView component={component} onSendAction={onSendAction} />;
    case 'button':
    case 'button_group':
      return <ActionButtons component={component} onSendAction={onSendAction} />;
    case 'status_card':
      return <StatusCardView component={component} />;
    default:
      return <UnknownComponent component={component} />;
  }
}