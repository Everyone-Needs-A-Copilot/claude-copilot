#!/usr/bin/env node
/**
 * Copilot Memory MCP Server
 *
 * Provides session memory with semantic search for Claude Code.
 * Replaces manual initiative file tracking with automated persistence.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

import { DatabaseClient } from './db/client.js';
import {
  memoryStore,
  memoryUpdate,
  memoryDelete,
  memoryGet,
  memoryList,
  memorySearch,
  initiativeStart,
  initiativeUpdate,
  initiativeGet,
  initiativeSlim,
  initiativeComplete,
  initiativeToMarkdown,
  detectCorrections,
  getPatterns,
  correctionStore,
  correctionGet,
  correctionList,
  correctionReview,
  correctionDelete,
  correctionStats,
  correctionMarkApplied,
  getReflectSummary,
  correctionRoute,
  correctionApply,
  correctionRouteBatch,
  correctionApplyBatch,
} from './tools/index.js';
import type {
  CorrectionDetectInput,
  CorrectionDetectOutput,
  CorrectionCapture,
  CorrectionStatus,
  CorrectionTarget,
  CorrectionReviewDecision,
  CorrectionRouteInput,
} from './types/corrections.js';
import { getInitiativeResource, getInitiativeSummary } from './resources/initiative-resource.js';
import { getContextResource } from './resources/context-resource.js';
import type { MemoryType, InitiativeStatus } from './types.js';

// Get configuration from environment
const PROJECT_PATH = process.cwd();
const MEMORY_PATH = process.env.MEMORY_PATH || undefined;
const WORKSPACE_ID = process.env.WORKSPACE_ID || undefined;
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';

// Initialize database
const db = new DatabaseClient(PROJECT_PATH, MEMORY_PATH, WORKSPACE_ID);

// Session ID for this run
const sessionId = `session_${Date.now()}`;

// Create MCP server
const server = new Server(
  {
    name: 'copilot-memory',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
      resources: {},
    },
  }
);

// Tool definitions
const TOOLS = [
  {
    name: 'memory_store',
    description: 'Store a new memory with automatic embedding generation for semantic search',
    inputSchema: {
      type: 'object',
      properties: {
        content: { type: 'string', description: 'The content to store' },
        type: {
          type: 'string',
          enum: ['decision', 'lesson', 'discussion', 'file', 'initiative', 'context', 'agent_improvement'],
          description: 'Type of memory'
        },
        tags: { type: 'array', items: { type: 'string' }, description: 'Optional tags for filtering' },
        metadata: {
          type: 'object',
          description: 'Optional metadata object. For agent_improvement type, must include: agentId, targetSection, currentContent, suggestedContent, rationale, status (pending|approved|rejected)'
        }
      },
      required: ['content', 'type']
    }
  },
  {
    name: 'memory_update',
    description: 'Update an existing memory',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Memory ID to update' },
        content: { type: 'string', description: 'New content (regenerates embedding)' },
        tags: { type: 'array', items: { type: 'string' }, description: 'New tags' },
        metadata: { type: 'object', description: 'New metadata' }
      },
      required: ['id']
    }
  },
  {
    name: 'memory_delete',
    description: 'Delete a memory',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Memory ID to delete' }
      },
      required: ['id']
    }
  },
  {
    name: 'memory_get',
    description: 'Get a memory by ID',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Memory ID' }
      },
      required: ['id']
    }
  },
  {
    name: 'memory_list',
    description: 'List memories with optional filters',
    inputSchema: {
      type: 'object',
      properties: {
        type: {
          type: 'string',
          enum: ['decision', 'lesson', 'discussion', 'file', 'initiative', 'context', 'agent_improvement'],
          description: 'Filter by type'
        },
        tags: { type: 'array', items: { type: 'string' }, description: 'Filter by tags (any match)' },
        agentId: { type: 'string', description: 'Filter by agentId in metadata (for agent_improvement type)' },
        limit: { type: 'number', description: 'Max results (default 20)' },
        offset: { type: 'number', description: 'Skip first N results' }
      }
    }
  },
  {
    name: 'memory_search',
    description: 'Semantic search across memories using natural language query',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Natural language search query' },
        type: {
          type: 'string',
          enum: ['decision', 'lesson', 'discussion', 'file', 'initiative', 'context', 'agent_improvement'],
          description: 'Filter by type'
        },
        agentId: { type: 'string', description: 'Filter by agentId in metadata (for agent_improvement type)' },
        limit: { type: 'number', description: 'Max results (default 10)' },
        threshold: { type: 'number', description: 'Similarity threshold 0-1 (default 0.7)' }
      },
      required: ['query']
    }
  },
  {
    name: 'initiative_start',
    description: 'Start a new initiative (archives any existing one)',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Initiative name' },
        goal: { type: 'string', description: 'Initiative goal' },
        status: {
          type: 'string',
          enum: ['NOT STARTED', 'IN PROGRESS', 'BLOCKED', 'READY FOR REVIEW', 'COMPLETE'],
          description: 'Initial status (default IN PROGRESS)'
        }
      },
      required: ['name']
    }
  },
  {
    name: 'initiative_update',
    description: 'Update the current initiative. Supports both slim mode (Task Copilot) and legacy mode.',
    inputSchema: {
      type: 'object',
      properties: {
        // NEW: Task Copilot integration
        taskCopilotLinked: { type: 'boolean', description: 'Whether initiative is linked to Task Copilot' },
        activePrdIds: { type: 'array', items: { type: 'string' }, description: 'Active PRD IDs from Task Copilot' },

        // KEEP: Permanent knowledge
        decisions: { type: 'array', items: { type: 'string' }, description: 'Decisions to add' },
        lessons: { type: 'array', items: { type: 'string' }, description: 'Lessons to add' },
        keyFiles: { type: 'array', items: { type: 'string' }, description: 'Key files to add' },

        // NEW: Slim resume context (max 100 chars each)
        currentFocus: { type: 'string', description: 'Current focus (max 100 chars, replaces resumeInstructions)' },
        nextAction: { type: 'string', description: 'Next action to take (max 100 chars)' },

        // DEPRECATED: Use Task Copilot instead (triggers warning if >10 items)
        completed: { type: 'array', items: { type: 'string' }, description: 'DEPRECATED: Tasks to add to completed (use Task Copilot)' },
        inProgress: { type: 'array', items: { type: 'string' }, description: 'DEPRECATED: Current in-progress tasks (use Task Copilot)' },
        blocked: { type: 'array', items: { type: 'string' }, description: 'DEPRECATED: Blocked items (use Task Copilot)' },
        resumeInstructions: { type: 'string', description: 'DEPRECATED: Resume instructions (use currentFocus + nextAction)' },

        status: {
          type: 'string',
          enum: ['NOT STARTED', 'IN PROGRESS', 'BLOCKED', 'READY FOR REVIEW', 'COMPLETE'],
          description: 'New status'
        }
      }
    }
  },
  {
    name: 'initiative_get',
    description: 'Get the current initiative state. Use lean mode (default) for session resume to save tokens. Use full mode when you need all decisions/lessons/keyFiles.',
    inputSchema: {
      type: 'object',
      properties: {
        mode: {
          type: 'string',
          enum: ['lean', 'full'],
          description: 'lean: ~150 tokens (excludes decisions, lessons, keyFiles), full: ~370 tokens (includes all fields). Default: lean'
        }
      }
    }
  },
  {
    name: 'initiative_slim',
    description: 'Slim down initiative by removing bloated task lists (completed, inProgress, blocked, resumeInstructions). Keeps permanent knowledge (decisions, lessons, keyFiles). Archives removed data to file.',
    inputSchema: {
      type: 'object',
      properties: {
        archiveDetails: {
          type: 'boolean',
          description: 'Save removed data to archive file before slimming (default: true)'
        }
      }
    }
  },
  {
    name: 'initiative_complete',
    description: 'Complete and archive the current initiative',
    inputSchema: {
      type: 'object',
      properties: {
        summary: { type: 'string', description: 'Optional completion summary' }
      }
    }
  },
  {
    name: 'health_check',
    description: 'Get server health and statistics',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'correction_detect',
    description: 'Detect correction patterns in user messages. Auto-extracts old/new values with confidence scoring.',
    inputSchema: {
      type: 'object',
      properties: {
        userMessage: { type: 'string', description: 'User message to analyze for corrections' },
        previousAgentOutput: { type: 'string', description: 'Previous agent output (for context)' },
        taskId: { type: 'string', description: 'Current task context' },
        agentId: { type: 'string', description: 'Current agent context' },
        threshold: { type: 'number', description: 'Minimum confidence threshold (default: 0.5)' }
      },
      required: ['userMessage']
    }
  },
  {
    name: 'correction_patterns_list',
    description: 'List all available correction detection patterns',
    inputSchema: {
      type: 'object',
      properties: {
        includeDisabled: { type: 'boolean', description: 'Include disabled patterns (default: false)' }
      }
    }
  },
  {
    name: 'correction_store',
    description: 'Store a detected correction for later review',
    inputSchema: {
      type: 'object',
      properties: {
        correction: { type: 'object', description: 'CorrectionCapture object from correction_detect' }
      },
      required: ['correction']
    }
  },
  {
    name: 'correction_get',
    description: 'Get a correction by ID',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Correction ID' }
      },
      required: ['id']
    }
  },
  {
    name: 'correction_list',
    description: 'List corrections with optional filters',
    inputSchema: {
      type: 'object',
      properties: {
        status: {
          type: 'string',
          enum: ['pending', 'approved', 'rejected', 'applied', 'expired'],
          description: 'Filter by status'
        },
        agentId: { type: 'string', description: 'Filter by agent ID' },
        target: {
          type: 'string',
          enum: ['skill', 'agent', 'memory', 'preference'],
          description: 'Filter by target type'
        },
        limit: { type: 'number', description: 'Max results (default: 20)' },
        offset: { type: 'number', description: 'Skip first N results' },
        includeExpired: { type: 'boolean', description: 'Include expired corrections (default: false)' }
      }
    }
  },
  {
    name: 'correction_review',
    description: 'Review a pending correction (approve, reject, or modify)',
    inputSchema: {
      type: 'object',
      properties: {
        correctionId: { type: 'string', description: 'Correction ID to review' },
        decision: {
          type: 'string',
          enum: ['approve', 'reject', 'modify'],
          description: 'Review decision'
        },
        rejectionReason: { type: 'string', description: 'Reason for rejection (if rejecting)' },
        modifiedContent: { type: 'string', description: 'Modified correction content (if modifying)' },
        notes: { type: 'string', description: 'Additional notes' }
      },
      required: ['correctionId', 'decision']
    }
  },
  {
    name: 'correction_delete',
    description: 'Delete a correction',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Correction ID to delete' }
      },
      required: ['id']
    }
  },
  {
    name: 'correction_stats',
    description: 'Get correction statistics',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'correction_mark_applied',
    description: 'Mark an approved correction as applied',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Correction ID to mark as applied' }
      },
      required: ['id']
    }
  },
  {
    name: 'reflect_summary',
    description: 'Get summary for /reflect command showing pending and recent corrections',
    inputSchema: {
      type: 'object',
      properties: {
        limit: { type: 'number', description: 'Max pending corrections to return (default: 10)' },
        agentId: { type: 'string', description: 'Filter by agent ID' }
      }
    }
  },
  {
    name: 'correction_route',
    description: 'Route an approved correction to its target (skill, agent, memory, or preference)',
    inputSchema: {
      type: 'object',
      properties: {
        correctionId: { type: 'string', description: 'Correction ID to route' },
        forceTarget: {
          type: 'string',
          enum: ['skill', 'agent', 'memory', 'preference'],
          description: 'Force specific target (override auto-detection)'
        },
        forceTargetId: { type: 'string', description: 'Force specific target ID' }
      },
      required: ['correctionId']
    }
  },
  {
    name: 'correction_apply',
    description: 'Apply a routed correction to its target (stores in memory, updates skill, etc.)',
    inputSchema: {
      type: 'object',
      properties: {
        correctionId: { type: 'string', description: 'Correction ID to apply' }
      },
      required: ['correctionId']
    }
  },
  {
    name: 'correction_route_batch',
    description: 'Route multiple approved corrections at once',
    inputSchema: {
      type: 'object',
      properties: {
        correctionIds: {
          type: 'array',
          items: { type: 'string' },
          description: 'Array of correction IDs to route'
        }
      },
      required: ['correctionIds']
    }
  },
  {
    name: 'correction_apply_batch',
    description: 'Apply multiple routed corrections at once',
    inputSchema: {
      type: 'object',
      properties: {
        correctionIds: {
          type: 'array',
          items: { type: 'string' },
          description: 'Array of correction IDs to apply'
        }
      },
      required: ['correctionIds']
    }
  }
];

// Handle list tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOLS
}));

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;
  const a = args as Record<string, unknown>;

  try {
    switch (name) {
      case 'memory_store': {
        const result = await memoryStore(db, {
          content: a.content as string,
          type: a.type as MemoryType,
          tags: a.tags as string[] | undefined,
          metadata: a.metadata as Record<string, unknown> | undefined
        }, sessionId);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'memory_update': {
        const result = await memoryUpdate(db, {
          id: a.id as string,
          content: a.content as string | undefined,
          tags: a.tags as string[] | undefined,
          metadata: a.metadata as Record<string, unknown> | undefined
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result, null, 2) : 'Memory not found' }] };
      }

      case 'memory_delete': {
        const result = memoryDelete(db, a.id as string);
        return { content: [{ type: 'text', text: result ? 'Deleted' : 'Memory not found' }] };
      }

      case 'memory_get': {
        const result = memoryGet(db, a.id as string);
        return { content: [{ type: 'text', text: result ? JSON.stringify(result, null, 2) : 'Memory not found' }] };
      }

      case 'memory_list': {
        const result = memoryList(db, {
          type: a.type as MemoryType | undefined,
          tags: a.tags as string[] | undefined,
          agentId: a.agentId as string | undefined,
          limit: a.limit as number | undefined,
          offset: a.offset as number | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'memory_search': {
        const result = await memorySearch(db, {
          query: a.query as string,
          type: a.type as MemoryType | undefined,
          agentId: a.agentId as string | undefined,
          limit: a.limit as number | undefined,
          threshold: a.threshold as number | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'initiative_start': {
        const result = initiativeStart(db, {
          name: a.name as string,
          goal: a.goal as string | undefined,
          status: a.status as InitiativeStatus | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'initiative_update': {
        const result = initiativeUpdate(db, {
          // NEW: Task Copilot integration
          taskCopilotLinked: a.taskCopilotLinked as boolean | undefined,
          activePrdIds: a.activePrdIds as string[] | undefined,
          // KEEP: Permanent knowledge
          decisions: a.decisions as string[] | undefined,
          lessons: a.lessons as string[] | undefined,
          keyFiles: a.keyFiles as string[] | undefined,
          // NEW: Slim resume context
          currentFocus: a.currentFocus as string | undefined,
          nextAction: a.nextAction as string | undefined,
          // DEPRECATED
          completed: a.completed as string[] | undefined,
          inProgress: a.inProgress as string[] | undefined,
          blocked: a.blocked as string[] | undefined,
          resumeInstructions: a.resumeInstructions as string | undefined,
          status: a.status as InitiativeStatus | undefined
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result, null, 2) : 'No active initiative' }] };
      }

      case 'initiative_get': {
        const result = initiativeGet(db, {
          mode: a.mode as 'lean' | 'full' | undefined
        });
        if (result) {
          // Add hint if initiative is bloated
          const totalTasks = result.completed.length + result.inProgress.length + result.blocked.length;
          const hasLongResume = result.resumeInstructions && result.resumeInstructions.length > 200;
          const hint = (totalTasks > 10 || hasLongResume)
            ? '\n\nHINT: This initiative has bloated task lists. Consider using initiative_slim to reduce context usage.'
            : '';
          return { content: [{ type: 'text', text: initiativeToMarkdown(result) + hint }] };
        }
        return { content: [{ type: 'text', text: 'No active initiative' }] };
      }

      case 'initiative_slim': {
        const result = initiativeSlim(db, {
          archiveDetails: a.archiveDetails !== undefined ? a.archiveDetails as boolean : true
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result, null, 2) : 'No active initiative' }] };
      }

      case 'initiative_complete': {
        const result = initiativeComplete(db, a.summary as string | undefined);
        return { content: [{ type: 'text', text: result ? `Initiative completed and archived:\n\n${initiativeToMarkdown(result)}` : 'No active initiative' }] };
      }

      case 'health_check': {
        const stats = db.getStats();
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              status: 'healthy',
              projectId: db.getProjectId(),
              sessionId,
              ...stats
            }, null, 2)
          }]
        };
      }

      case 'correction_detect': {
        const input: CorrectionDetectInput = {
          userMessage: a.userMessage as string,
          previousAgentOutput: a.previousAgentOutput as string | undefined,
          taskId: a.taskId as string | undefined,
          agentId: a.agentId as string | undefined,
          threshold: a.threshold as number | undefined,
        };
        const result: CorrectionDetectOutput = detectCorrections(input);
        // Set project ID on any detected corrections
        for (const correction of result.corrections) {
          correction.projectId = db.getProjectId();
        }
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'correction_patterns_list': {
        const patterns = getPatterns(a.includeDisabled as boolean | undefined);
        return { content: [{ type: 'text', text: JSON.stringify(patterns, null, 2) }] };
      }

      case 'correction_store': {
        const correction = a.correction as CorrectionCapture;
        const result = correctionStore(db, correction);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'correction_get': {
        const correction = correctionGet(db, a.id as string);
        return { content: [{ type: 'text', text: correction ? JSON.stringify(correction, null, 2) : 'Correction not found' }] };
      }

      case 'correction_list': {
        const corrections = correctionList(db, {
          status: a.status as CorrectionStatus | undefined,
          agentId: a.agentId as string | undefined,
          target: a.target as CorrectionTarget | undefined,
          limit: a.limit as number | undefined,
          offset: a.offset as number | undefined,
          includeExpired: a.includeExpired as boolean | undefined,
        });
        return { content: [{ type: 'text', text: JSON.stringify(corrections, null, 2) }] };
      }

      case 'correction_review': {
        const decision: CorrectionReviewDecision = {
          correctionId: a.correctionId as string,
          decision: a.decision as 'approve' | 'reject' | 'modify',
          rejectionReason: a.rejectionReason as string | undefined,
          modifiedContent: a.modifiedContent as string | undefined,
          notes: a.notes as string | undefined,
        };
        const result = correctionReview(db, decision);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'correction_delete': {
        const deleted = correctionDelete(db, a.id as string);
        return { content: [{ type: 'text', text: deleted ? 'Deleted' : 'Correction not found' }] };
      }

      case 'correction_stats': {
        const stats = correctionStats(db);
        return { content: [{ type: 'text', text: JSON.stringify(stats, null, 2) }] };
      }

      case 'correction_mark_applied': {
        const result = correctionMarkApplied(db, a.id as string);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'reflect_summary': {
        const summary = getReflectSummary(db, {
          limit: a.limit as number | undefined,
          agentId: a.agentId as string | undefined,
        });
        return { content: [{ type: 'text', text: JSON.stringify(summary, null, 2) }] };
      }

      case 'correction_route': {
        const input: CorrectionRouteInput = {
          correctionId: a.correctionId as string,
          forceTarget: a.forceTarget as CorrectionTarget | undefined,
          forceTargetId: a.forceTargetId as string | undefined,
        };
        const result = correctionRoute(db, input, sessionId);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'correction_apply': {
        const result = await correctionApply(db, a.correctionId as string, sessionId);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'correction_route_batch': {
        const results = correctionRouteBatch(db, a.correctionIds as string[], sessionId);
        return { content: [{ type: 'text', text: JSON.stringify(results, null, 2) }] };
      }

      case 'correction_apply_batch': {
        const results = await correctionApplyBatch(db, a.correctionIds as string[], sessionId);
        return { content: [{ type: 'text', text: JSON.stringify(results, null, 2) }] };
      }

      default:
        return { content: [{ type: 'text', text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return { content: [{ type: 'text', text: `Error: ${message}` }], isError: true };
  }
});

// Resource definitions
const RESOURCES = [
  {
    uri: 'memory://initiative/current',
    name: 'Current Initiative',
    description: 'The current work initiative in markdown format',
    mimeType: 'text/markdown'
  },
  {
    uri: 'memory://context/project',
    name: 'Project Context',
    description: 'Project memory context including recent decisions and lessons',
    mimeType: 'text/markdown'
  }
];

// Handle list resources
server.setRequestHandler(ListResourcesRequestSchema, async () => ({
  resources: RESOURCES
}));

// Handle read resource
server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  const { uri } = request.params;

  switch (uri) {
    case 'memory://initiative/current': {
      const resource = getInitiativeResource(db);
      if (resource) {
        return { contents: [{ uri: resource.uri, mimeType: resource.mimeType, text: resource.content }] };
      }
      return { contents: [{ uri, mimeType: 'text/plain', text: 'No active initiative' }] };
    }

    case 'memory://context/project': {
      const resource = getContextResource(db);
      return { contents: [{ uri: resource.uri, mimeType: resource.mimeType, text: resource.content }] };
    }

    default:
      throw new Error(`Unknown resource: ${uri}`);
  }
});

// Start server
async function main() {
  if (LOG_LEVEL === 'debug') {
    console.error('Copilot Memory server starting...');
    console.error(`Project: ${PROJECT_PATH}`);
    console.error(`Workspace ID: ${WORKSPACE_ID || '(auto-generated)'}`);
    console.error(`Project ID: ${db.getProjectId()}`);
    console.error(`Session: ${sessionId}`);
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);

  if (LOG_LEVEL === 'debug') {
    console.error('Copilot Memory server running');
  }
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});

// Cleanup on exit
process.on('SIGINT', () => {
  db.close();
  process.exit(0);
});

process.on('SIGTERM', () => {
  db.close();
  process.exit(0);
});
