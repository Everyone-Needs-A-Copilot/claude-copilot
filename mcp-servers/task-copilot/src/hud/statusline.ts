/**
 * Statusline Component for Progress HUD
 *
 * Displays current task/stream progress with model and token estimates.
 * Format: [Stream-A] 2/3 tasks | opus | ~1.2k tokens
 *
 * @see PRD-omc-learnings (Stream C: Progress HUD)
 * @module hud/statusline
 */

import type { StatuslineState, ProgressEvent } from '../types/omc-features.js';

/**
 * Model display configuration
 */
const MODEL_INDICATORS = {
  haiku: { symbol: 'h', color: '\x1b[32m' }, // green
  sonnet: { symbol: 's', color: '\x1b[33m' }, // yellow
  opus: { symbol: 'o', color: '\x1b[35m' }, // magenta
} as const;

const RESET_COLOR = '\x1b[0m';

/**
 * Status symbol configuration
 */
const STATUS_SYMBOLS = {
  pending: '⏸',
  in_progress: '▶',
  blocked: '⚠',
  completed: '✓',
} as const;

/**
 * Options for statusline rendering
 */
export interface StatuslineOptions {
  /** Whether to use color output (default: true) */
  useColor?: boolean;

  /** Whether to use unicode symbols (default: true) */
  useUnicode?: boolean;

  /** Maximum width in characters (default: 80) */
  maxWidth?: number;

  /** Whether to show file changes (default: false) */
  showFiles?: boolean;
}

/**
 * Rendered statusline result
 */
export interface RenderedStatusline {
  /** Formatted text output */
  text: string;

  /** Estimated width in characters */
  width: number;

  /** Timestamp of render */
  timestamp: string;
}

/**
 * Format bytes to human-readable token estimate
 */
function formatTokens(count: number): string {
  if (count < 1000) {
    return `${count}`;
  } else if (count < 1000000) {
    return `${(count / 1000).toFixed(1)}k`;
  } else {
    return `${(count / 1000000).toFixed(1)}m`;
  }
}

/**
 * Truncate text to fit max width
 */
function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) {
    return text;
  }
  return text.slice(0, maxLength - 3) + '...';
}

/**
 * Calculate progress percentage from task state
 */
export function calculateProgress(state: StatuslineState): number {
  // If progress is explicitly set, use it
  if (state.progressPercent > 0) {
    return state.progressPercent;
  }

  // Otherwise derive from status
  switch (state.status) {
    case 'pending':
      return 0;
    case 'in_progress':
      return 50;
    case 'completed':
      return 100;
    case 'blocked':
      return state.progressPercent || 0;
    default:
      return 0;
  }
}

/**
 * Render statusline from state
 */
export function renderStatusline(
  state: StatuslineState,
  model: 'haiku' | 'sonnet' | 'opus' = 'sonnet',
  tokenEstimate: number = 0,
  options: StatuslineOptions = {}
): RenderedStatusline {
  const {
    useColor = true,
    useUnicode = true,
    maxWidth = 80,
    showFiles = false,
  } = options;

  // Build components
  const parts: string[] = [];

  // Stream/Task identifier
  if (state.streamId) {
    parts.push(`[${state.streamId}]`);
  }

  // Progress indicator
  const progress = calculateProgress(state);
  const statusSymbol = useUnicode ? STATUS_SYMBOLS[state.status] : state.status[0].toUpperCase();
  parts.push(`${statusSymbol} ${progress}%`);

  // Model indicator
  const modelConfig = MODEL_INDICATORS[model];
  const modelDisplay = useColor
    ? `${modelConfig.color}${model}${RESET_COLOR}`
    : model;
  parts.push(modelDisplay);

  // Token estimate / budget
  if (tokenEstimate > 0 || state.tokenBudget) {
    if (state.tokenBudget) {
      const usageDisplay = formatTokens(tokenEstimate);
      const budgetDisplay = formatTokens(state.tokenBudget);
      const overBudget = tokenEstimate > state.tokenBudget;
      parts.push(`~${usageDisplay}/${budgetDisplay} tokens${overBudget ? ' !' : ''}`);
    } else {
      parts.push(`~${formatTokens(tokenEstimate)} tokens`);
    }
  }

  // Optional: Active files
  if (showFiles && state.activeFiles.length > 0) {
    const fileCount = state.activeFiles.length;
    const fileDisplay = fileCount === 1
      ? truncate(state.activeFiles[0], 20)
      : `${fileCount} files`;
    parts.push(fileDisplay);
  }

  // Combine parts
  const text = parts.join(' | ');
  const truncatedText = truncate(text, maxWidth);

  return {
    text: truncatedText,
    width: truncatedText.length,
    timestamp: new Date().toISOString(),
  };
}

/**
 * Create statusline updater that maintains state
 */
export class StatuslineUpdater {
  private state: StatuslineState;
  private model: 'haiku' | 'sonnet' | 'opus' = 'sonnet';
  private tokenEstimate: number = 0;
  private options: StatuslineOptions;
  private listeners: Array<(rendered: RenderedStatusline) => void> = [];

  constructor(initialState: StatuslineState, options: StatuslineOptions = {}) {
    this.state = initialState;
    this.options = options;
  }

  /**
   * Update state and re-render
   */
  updateState(state: Partial<StatuslineState>): RenderedStatusline {
    this.state = { ...this.state, ...state };
    return this.render();
  }

  /**
   * Update model being used
   */
  updateModel(model: 'haiku' | 'sonnet' | 'opus'): RenderedStatusline {
    this.model = model;
    return this.render();
  }

  /**
   * Update token estimate
   */
  updateTokens(tokens: number): RenderedStatusline {
    this.tokenEstimate = tokens;
    return this.render();
  }

  /**
   * Update token budget
   */
  updateTokenBudget(tokens: number): RenderedStatusline {
    this.state.tokenBudget = tokens;
    return this.render();
  }

  /**
   * Handle progress event
   */
  handleEvent(event: ProgressEvent): RenderedStatusline {
    switch (event.type) {
      case 'task_started':
        this.state.status = 'in_progress';
        break;

      case 'task_completed':
        this.state.status = 'completed';
        this.state.progressPercent = 100;
        break;

      case 'task_updated':
        // Extract progress from payload
        if (typeof event.payload.progress === 'number') {
          this.state.progressPercent = event.payload.progress;
        }
        break;

      case 'file_modified':
        // Add file to active list
        if (typeof event.payload.filePath === 'string') {
          const filePath = event.payload.filePath;
          if (!this.state.activeFiles.includes(filePath)) {
            this.state.activeFiles = [...this.state.activeFiles, filePath];
          }
        }
        break;

      case 'agent_switched':
        // Update agent ID
        if (typeof event.payload.agentId === 'string') {
          this.state.agentId = event.payload.agentId;
        }
        break;
    }

    this.state.lastUpdate = event.timestamp;
    return this.render();
  }

  /**
   * Render current state
   */
  render(): RenderedStatusline {
    const rendered = renderStatusline(this.state, this.model, this.tokenEstimate, this.options);

    // Notify listeners
    this.listeners.forEach(listener => listener(rendered));

    return rendered;
  }

  /**
   * Subscribe to render updates
   */
  subscribe(listener: (rendered: RenderedStatusline) => void): () => void {
    this.listeners.push(listener);

    // Return unsubscribe function
    return () => {
      const index = this.listeners.indexOf(listener);
      if (index > -1) {
        this.listeners.splice(index, 1);
      }
    };
  }

  /**
   * Get current state
   */
  getState(): StatuslineState {
    return { ...this.state };
  }
}

/**
 * Create a simple statusline updater
 */
export function createStatusline(
  taskId: string,
  taskTitle: string,
  streamId?: string,
  options: StatuslineOptions = {}
): StatuslineUpdater {
  const initialState: StatuslineState = {
    taskId,
    taskTitle,
    status: 'pending',
    progressPercent: 0,
    streamId,
    activeFiles: [],
    lastUpdate: new Date().toISOString(),
  };

  return new StatuslineUpdater(initialState, options);
}
