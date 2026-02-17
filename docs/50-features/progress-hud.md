# Progress HUD - Live Status Display

Real-time terminal UI components for displaying task progress, model usage, and token estimates.

## Overview

The Progress HUD provides visual feedback during task execution with terminal-aware rendering.

**Location:** `mcp-servers/task-copilot/src/hud/`

| File | Purpose |
|------|---------|
| `statusline.ts` | Main statusline component |
| `terminal-compat.ts` | Terminal capability detection and fallbacks |
| `websocket-client.ts` | Real-time event streaming (optional) |

---

## Statusline Component

Displays current task/stream progress in a compact format.

### Format

```
[Stream-A] ▶ 50% | sonnet | ~1.2k tokens
[Stream-B] ✓ 100% | haiku | ~500 tokens
[Stream-C] ⚠ 25% | opus | ~3.4k tokens
```

With a token budget configured:

```
[Stream-A] ▶ 50% | sonnet | ~1.2k/2.5k tokens
```

### Components

| Part | Description | Example |
|------|-------------|---------|
| Stream ID | Task/stream identifier | `[Stream-A]` |
| Status | Unicode symbol for state | `▶` (in progress) |
| Progress | Percentage complete | `50%` |
| Model | Current model with color | `sonnet` (yellow) |
| Tokens | Estimated token usage | `~1.2k tokens` |

### Status Symbols

| Status | Unicode | ASCII | Meaning |
|--------|---------|-------|---------|
| pending | ⏸ | P | Not started |
| in_progress | ▶ | > | Currently running |
| blocked | ⚠ | ! | Blocked by dependency |
| completed | ✓ | * | Finished |

### Model Colors

| Model | ANSI Color | Code |
|-------|------------|------|
| haiku | Green | `\x1b[32m` |
| sonnet | Yellow | `\x1b[33m` |
| opus | Magenta | `\x1b[35m` |

---

## API Reference

### createStatusline

Creates a statusline updater instance.

```typescript
import { createStatusline } from 'task-copilot/hud/statusline';

const hud = createStatusline(
  'TASK-123',      // taskId
  'Fix auth bug',  // taskTitle
  'Stream-A',      // streamId (optional)
  { useColor: true, useUnicode: true, maxWidth: 80 }
);
```

### StatuslineUpdater

The updater maintains state and re-renders on changes.

```typescript
// Update task state
hud.updateState({ status: 'in_progress', progressPercent: 50 });

// Update model being used
hud.updateModel('sonnet');

// Update token estimate
hud.updateTokens(1200);

// Get rendered output
const output = hud.render();
// → { text: '[Stream-A] ▶ 50% | sonnet | ~1.2k tokens', width: 42, timestamp: '...' }
```

### Event Handling

Handle progress events for real-time updates:

```typescript
hud.handleEvent({
  type: 'task_started',
  taskId: 'TASK-123',
  timestamp: new Date().toISOString(),
  payload: {}
});

hud.handleEvent({
  type: 'task_updated',
  taskId: 'TASK-123',
  timestamp: new Date().toISOString(),
  payload: { progress: 75 }
});

hud.handleEvent({
  type: 'file_modified',
  taskId: 'TASK-123',
  timestamp: new Date().toISOString(),
  payload: { filePath: 'src/auth/login.ts' }
});
```

### Event Types

| Event | Payload | Effect |
|-------|---------|--------|
| `task_started` | - | Sets status to `in_progress` |
| `task_completed` | - | Sets status to `completed`, progress to 100% |
| `task_updated` | `{ progress: number }` | Updates progress percentage |
| `file_modified` | `{ filePath: string }` | Adds to active files list |
| `agent_switched` | `{ agentId: string }` | Updates current agent |

### Subscribe to Updates

```typescript
const unsubscribe = hud.subscribe((rendered) => {
  process.stdout.write('\r' + rendered.text);
});

// Later: stop receiving updates
unsubscribe();
```

---

## Terminal Compatibility

The `terminal-compat.ts` module detects terminal capabilities and provides fallbacks.

### detectTerminalCapabilities

```typescript
import { detectTerminalCapabilities } from 'task-copilot/hud/terminal-compat';

const caps = detectTerminalCapabilities();
// {
//   supportsColor: true,
//   supportsUnicode: true,
//   width: 120,
//   height: 40,
//   colorDepth: 24,
//   termType: 'xterm-256color',
//   isCI: false,
//   isTTY: true
// }
```

### Capability Detection

| Capability | Detection Method |
|------------|------------------|
| Color | `TERM`, `FORCE_COLOR`, `NO_COLOR` env vars |
| Unicode | `LANG`, `LC_ALL` for UTF-8 |
| Color Depth | `COLORTERM`, `TERM` for 256color/truecolor |
| TTY | `process.stdout.isTTY` |
| CI | `CI`, `GITHUB_ACTIONS`, `TRAVIS`, etc. |

### Progress Bar Rendering

```typescript
import { renderProgressBar, ASCII_PROGRESS_BAR, UNICODE_PROGRESS_BAR } from 'task-copilot/hud/terminal-compat';

// ASCII fallback (default)
renderProgressBar(50);
// → [##########----------]

// Unicode style
renderProgressBar(75, UNICODE_PROGRESS_BAR);
// → [███████████████░░░░░]

// Handles edge cases
renderProgressBar(0);    // → [--------------------]
renderProgressBar(100);  // → [####################]
renderProgressBar(-10);  // → [--------------------] (clamped)
renderProgressBar(150);  // → [####################] (clamped)
```

### Progress Bar Styles

| Style | Filled | Empty | Example |
|-------|--------|-------|---------|
| ASCII | `#` | `-` | `[#####---------------]` |
| Unicode | `█` | `░` | `[█████░░░░░░░░░░░░░░░]` |

### TerminalWriter

A convenience class for terminal output with capability awareness.

```typescript
import { createTerminalWriter } from 'task-copilot/hud/terminal-compat';

const writer = createTerminalWriter();

// Check capabilities
writer.supports('color');   // true/false
writer.supports('unicode'); // true/false

// Write with colors
writer.writeLine(writer.colorize('Success!', 'green'));

// Update line (clear and rewrite)
writer.updateLine('Progress: 50%');

// Render progress bar based on capabilities
const bar = writer.renderProgress(75);
```

### ANSI Utilities

```typescript
import { ANSI, stripAnsi, getVisibleWidth } from 'task-copilot/hud/terminal-compat';

// ANSI codes
ANSI.clearLine;      // Clear entire line
ANSI.cursorStart;    // Move cursor to start
ANSI.hideCursor;     // Hide cursor
ANSI.showCursor;     // Show cursor
ANSI.reset;          // Reset formatting
ANSI.colors.green;   // Green text
ANSI.bgColors.red;   // Red background

// Strip ANSI codes from text
stripAnsi('\x1b[32mGreen text\x1b[0m');
// → 'Green text'

// Get visible width (excluding ANSI)
getVisibleWidth('\x1b[32mHello\x1b[0m');
// → 5
```

### Text Fitting

```typescript
import { fitToWidth } from 'task-copilot/hud/terminal-compat';

fitToWidth('This is a very long text that needs truncation', 20);
// → 'This is a very lo...'
```

---

## WebSocket Client (Optional)

For real-time event streaming from external sources.

```typescript
import { TaskCopilotClient } from 'task-copilot/hud/websocket-client';

const client = new TaskCopilotClient('http://localhost:3456');

// Subscribe to task events
client.subscribeToTask('TASK-123', (event) => {
  console.log('Event:', event.type, event.payload);
});

// Poll for events (if WebSocket not available)
const events = await client.pollEvents('TASK-123', lastEventTime);
```

---

## Usage Examples

### Basic Statusline

```typescript
import { createStatusline } from 'task-copilot/hud/statusline';

const hud = createStatusline('TASK-001', 'Implement feature', 'Stream-A');

// Start task
hud.updateState({ status: 'in_progress' });
hud.updateModel('sonnet');
console.log(hud.render().text);
// → [Stream-A] ▶ 50% | sonnet

// Update progress
hud.updateState({ progressPercent: 75 });
hud.updateTokens(2500);
console.log(hud.render().text);
// → [Stream-A] ▶ 75% | sonnet | ~2.5k tokens

// Complete
hud.updateState({ status: 'completed', progressPercent: 100 });
console.log(hud.render().text);
// → [Stream-A] ✓ 100% | sonnet | ~2.5k tokens
```

### Terminal-Aware Output

```typescript
import { createTerminalWriter, detectTerminalCapabilities } from 'task-copilot/hud/terminal-compat';

const caps = detectTerminalCapabilities();
const writer = createTerminalWriter(caps);

if (caps.isTTY) {
  // Interactive terminal: use progress bar
  writer.updateLine(`Progress: ${writer.renderProgress(50)}`);
} else {
  // Non-TTY (CI, piped): simple text
  writer.writeLine('Progress: 50%');
}
```

### Capability-Based Rendering

```typescript
import { createStatusline } from 'task-copilot/hud/statusline';
import { detectTerminalCapabilities } from 'task-copilot/hud/terminal-compat';

const caps = detectTerminalCapabilities();

const hud = createStatusline('TASK-001', 'My Task', 'Stream-A', {
  useColor: caps.supportsColor,
  useUnicode: caps.supportsUnicode,
  maxWidth: caps.width
});
```

---

## CI/CD Considerations

In CI environments:

- Color is disabled by default (unless `FORCE_COLOR` set)
- Unicode may fall back to ASCII
- TTY detection returns false
- Progress bars use ASCII style

Force capabilities in CI:

```bash
FORCE_COLOR=1 npm test  # Enable colors
```

---

## Related Documentation

- [Ecomode](./ecomode.md) - Model routing that feeds into HUD
- [Magic Keywords](./magic-keywords.md) - Task keywords
