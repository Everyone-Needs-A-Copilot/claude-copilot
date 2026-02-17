# Progress HUD Components

This directory contains the Progress HUD implementation from the OMC Learnings Integration initiative (Stream C).

## Components

### 1. Statusline (`statusline.ts`)

Displays current task/stream progress with model and token estimates.

**Features:**
- Progress indicators with status symbols (⏸ pending, ▶ in_progress, ⚠ blocked, ✓ completed)
- Model display with color coding (haiku=green, sonnet=yellow, opus=magenta)
- Token count estimates with human-readable formatting (1.2k, 1.5m)
- Optional file change tracking
- Event-driven updates via StatuslineUpdater class

**Usage:**
```typescript
import { createStatusline } from './statusline.js';

const statusline = createStatusline('TASK-123', 'Implement feature', 'Stream-A');
statusline.updateModel('opus');
statusline.updateTokens(1200);
statusline.updateTokenBudget(2500);

const rendered = statusline.render();
// Output: [Stream-A] ▶ 50% | opus | ~1.2k/2.5k tokens
```

### 2. WebSocket Client (`websocket-client.ts`)

Connects to Claude Code's status events or falls back to polling Task Copilot.

**Features:**
- WebSocket connection with auto-reconnect
- Automatic fallback to HTTP polling on connection failure
- Task subscription management
- Progress event emission (task_started, task_updated, task_completed, file_modified, agent_switched)
- Custom data fetcher support for testing

**Usage:**
```typescript
import { createProgressClient } from './websocket-client.js';

const client = await createProgressClient({
  url: 'ws://localhost:3100',
  enablePollingFallback: true,
  pollingInterval: 1000,
});

client.on('progress', (event) => {
  console.log('Progress event:', event);
});

client.subscribeTask('TASK-123');
```

### 3. Terminal Compatibility (`terminal-compat.ts`)

Detects terminal capabilities and provides fallback rendering.

**Features:**
- Terminal capability detection (color, unicode, width, TTY)
- CI environment detection
- Progress bar rendering (unicode or ASCII fallback)
- ANSI escape sequence utilities
- Safe colorization with automatic fallback
- Text width calculation (excluding ANSI codes)
- TerminalWriter class for capability-aware output

**Usage:**
```typescript
import { createTerminalWriter, detectTerminalCapabilities } from './terminal-compat.js';

const capabilities = detectTerminalCapabilities();
const writer = createTerminalWriter(capabilities);

// Render progress bar (automatically chooses unicode or ASCII)
const bar = writer.renderProgress(75);
// Unicode: [███████████████░░░░░]
// ASCII:   [###############-----]

// Safe colorization
const text = writer.colorize('Success', 'green');
// Color terminals: "\x1b[32mSuccess\x1b[0m"
// Non-color: "Success"
```

## Integration Example

Combine all three components for a complete HUD:

```typescript
import { createStatusline } from './statusline.js';
import { createProgressClient } from './websocket-client.js';
import { createTerminalWriter } from './terminal-compat.js';

// Setup
const writer = createTerminalWriter();
const statusline = createStatusline('TASK-123', 'Implement feature', 'Stream-A', {
  useColor: writer.supports('color'),
  useUnicode: writer.supports('unicode'),
  maxWidth: writer.getCapabilities().width - 10,
});

const client = await createProgressClient();

// Connect events
client.on('progress', (event) => {
  const rendered = statusline.handleEvent(event);
  writer.updateLine(rendered.text);
});

client.subscribeTask('TASK-123');
```

## Type Imports

All HUD types are defined in `../types/omc-features.ts`:

```typescript
import type {
  StatuslineState,
  ProgressEvent,
  HudConfig,
} from '../types/omc-features.js';
```

## Testing

Each component is designed to be testable in isolation:

- **Statusline**: Pure functions with dependency injection
- **WebSocket Client**: Custom fetcher support for mocking
- **Terminal Compatibility**: Explicit capability objects for deterministic testing

## Future Enhancements

Potential improvements for future iterations:

1. **Keyboard shortcuts** - Add interactive controls (pause, skip, view details)
2. **Multi-stream display** - Show progress for all parallel streams
3. **Metrics dashboard** - Token usage trends, velocity tracking
4. **Notification integration** - System notifications for task completion
5. **Log streaming** - Real-time log viewer alongside progress

## Performance Considerations

- WebSocket client uses exponential backoff for reconnection
- Polling mode respects configurable intervals (default 1s)
- Terminal width detection caches capabilities
- ANSI code stripping uses compiled regex for efficiency
- Progress bar rendering pre-calculates width once per style

## Browser Compatibility

While designed for Node.js terminals, the core logic is browser-compatible:

- Replace `process.stdout` with DOM elements
- Use browser WebSocket API (same interface)
- Detect capabilities via CSS media queries or feature detection
- Render progress with HTML/CSS instead of ANSI codes
