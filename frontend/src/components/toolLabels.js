const WIDGET_NAMES = {
  health_wellness: 'Health & Wellness',
  calendar: 'Calendar',
  markets: 'Markets',
  media: 'Media',
  nutrition: 'Nutrition',
  infrastructure: 'Infrastructure',
  system_metrics: 'System Metrics',
  prod_health: 'Prod Health',
  quick_links: 'Quick Links',
};

const SOURCE_NAMES = {
  health: 'Health',
  markets: 'Markets',
  infra: 'Infrastructure',
  calendar: 'Calendar',
  system: 'System Metrics',
  prod_health: 'Prod Health',
};

export function toolLabel(call) {
  const { name, input = {} } = call;
  if (name === 'update_layout') {
    const w = WIDGET_NAMES[input.widget] || input.widget;
    if (input.action === 'move') return `Move ${w} → slot ${input.position}`;
    if (input.action === 'hide') return `Hide ${w}`;
    if (input.action === 'show') return `Show ${w}`;
    if (input.action === 'reset') return 'Reset layout';
    return 'Update layout';
  }
  if (name === 'query_data') {
    return `Query ${SOURCE_NAMES[input.source] || input.source}`;
  }
  if (name === 'update_ticker') {
    return `Ticker → ${(input.items || []).join(', ')}`;
  }
  if (name === 'manage_sources') {
    if (input.action === 'list') return 'List sources';
    if (input.action === 'test') return `Test ${input.connector_id || 'source'}`;
    if (input.action === 'remove') return `Remove ${input.connector_id || 'source'}`;
    return 'Manage sources';
  }
  return name;
}
