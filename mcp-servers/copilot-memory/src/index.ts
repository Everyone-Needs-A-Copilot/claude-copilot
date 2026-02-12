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
  storeCorrection,
  updateCorrectionStatus,
  listCorrections,
  getCorrectionStats,
  routeCorrection,
  applyCorrection,
  getRoutingSummary
} from './tools/index.js';
import type { CorrectionStatus, CorrectionTarget } from './types/corrections.js';
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
    description: 'Store a new memory (auto-generates embedding for search)',
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
    description: 'Semantic search across memories using natural language',
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
    description: 'Update the current initiative',
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
    description: 'Get the current initiative. Lean mode (default) excludes decisions/lessons/keyFiles.',
    inputSchema: {
      type: 'object',
      properties: {
        mode: {
          type: 'string',
          enum: ['lean', 'full'],
          description: 'lean (default): excludes decisions/lessons/keyFiles. full: all fields.'
        }
      }
    }
  },
  {
    name: 'initiative_slim',
    description: 'Slim down initiative by clearing task lists. Keeps decisions/lessons/keyFiles, archives removed data.',
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
    description: 'Detect correction patterns in user messages. Returns matches, confidence, and extracted old/new values.',
    inputSchema: {
      type: 'object',
      properties: {
        userMessage: { type: 'string', description: 'User message to analyze for correction patterns' },
        previousAgentOutput: { type: 'string', description: 'Previous agent output (for context)' },
        taskId: { type: 'string', description: 'Current task context' },
        agentId: { type: 'string', description: 'Current agent context (me, ta, qa, etc.)' },
        threshold: { type: 'number', description: 'Minimum confidence threshold 0-1 (default: 0.5)' },
        autoStore: { type: 'boolean', description: 'Automatically store detected corrections (default: false)' }
      },
      required: ['userMessage']
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
        agentId: { type: 'string', description: 'Filter by agent (me, ta, qa, etc.)' },
        target: {
          type: 'string',
          enum: ['skill', 'agent', 'memory', 'preference'],
          description: 'Filter by target type'
        },
        limit: { type: 'number', description: 'Max results (default: 20)' },
        includeExpired: { type: 'boolean', description: 'Include expired corrections (default: false)' }
      }
    }
  },
  {
    name: 'correction_update',
    description: 'Update a correction status (approve, reject, or mark applied)',
    inputSchema: {
      type: 'object',
      properties: {
        correctionId: { type: 'string', description: 'Correction ID to update' },
        status: {
          type: 'string',
          enum: ['approved', 'rejected', 'applied'],
          description: 'New status'
        },
        rejectionReason: { type: 'string', description: 'Reason for rejection (if rejecting)' }
      },
      required: ['correctionId', 'status']
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
    name: 'correction_route',
    description: 'Get routing info for a correction (dry-run, does not apply)',
    inputSchema: {
      type: 'object',
      properties: {
        correctionId: { type: 'string', description: 'Correction ID to route' },
        forceTarget: {
          type: 'string',
          enum: ['skill', 'agent', 'memory', 'preference'],
          description: 'Override auto-detected target'
        },
        forceTargetId: { type: 'string', description: 'Override target ID (skill name, agent id, etc.)' }
      },
      required: ['correctionId']
    }
  },
  {
    name: 'correction_apply',
    description: 'Apply an approved correction and return instructions for the responsible agent',
    inputSchema: {
      type: 'object',
      properties: {
        correctionId: { type: 'string', description: 'Correction ID to apply' }
      },
      required: ['correctionId']
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
        const result = detectCorrections({
          userMessage: a.userMessage as string,
          previousAgentOutput: a.previousAgentOutput as string | undefined,
          taskId: a.taskId as string | undefined,
          agentId: a.agentId as string | undefined,
          threshold: a.threshold as number | undefined
        }, db.getProjectId());

        // Auto-store if requested and corrections detected
        if (a.autoStore && result.detected && result.corrections.length > 0) {
          for (const correction of result.corrections) {
            storeCorrection(db, correction, sessionId);
          }
        }

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              detected: result.detected,
              patternMatchCount: result.patternMatchCount,
              maxConfidence: result.maxConfidence,
              suggestedAction: result.suggestedAction,
              corrections: result.corrections.map(c => ({
                id: c.id,
                originalContent: c.originalContent,
                correctedContent: c.correctedContent,
                target: c.target,
                targetId: c.targetId,
                confidence: c.confidence,
                matchedPatterns: c.matchedPatterns.map(p => p.patternId),
                status: c.status
              }))
            }, null, 2)
          }]
        };
      }

      case 'correction_list': {
        const corrections = listCorrections(db, {
          status: a.status as CorrectionStatus | undefined,
          agentId: a.agentId as string | undefined,
          target: a.target as CorrectionTarget | undefined,
          limit: (a.limit as number) || 20,
          includeExpired: a.includeExpired as boolean | undefined
        });

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              count: corrections.length,
              corrections: corrections.map(c => ({
                id: c.id,
                originalContent: c.originalContent.substring(0, 100) + (c.originalContent.length > 100 ? '...' : ''),
                correctedContent: c.correctedContent.substring(0, 100) + (c.correctedContent.length > 100 ? '...' : ''),
                target: c.target,
                targetId: c.targetId,
                confidence: c.confidence,
                status: c.status,
                createdAt: c.createdAt
              }))
            }, null, 2)
          }]
        };
      }

      case 'correction_update': {
        const reviewMetadata = a.rejectionReason
          ? { rejectionReason: a.rejectionReason as string }
          : undefined;

        const success = updateCorrectionStatus(
          db,
          a.correctionId as string,
          a.status as CorrectionStatus,
          reviewMetadata
        );

        return {
          content: [{
            type: 'text',
            text: success
              ? `Correction ${a.correctionId} updated to ${a.status}`
              : `Correction ${a.correctionId} not found`
          }]
        };
      }

      case 'correction_stats': {
        const stats = getCorrectionStats(db);

        return {
          content: [{
            type: 'text',
            text: JSON.stringify(stats, null, 2)
          }]
        };
      }

      case 'correction_route': {
        const route = routeCorrection(
          db,
          a.correctionId as string,
          a.forceTarget as CorrectionTarget | undefined,
          a.forceTargetId as string | undefined
        );

        if (!route) {
          return {
            content: [{
              type: 'text',
              text: `Correction ${a.correctionId} not found`
            }],
            isError: true
          };
        }

        return {
          content: [{
            type: 'text',
            text: JSON.stringify(route, null, 2)
          }]
        };
      }

      case 'correction_apply': {
        const result = applyCorrection(db, a.correctionId as string);

        if (!result.success) {
          return {
            content: [{
              type: 'text',
              text: result.message
            }],
            isError: true
          };
        }

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: true,
              message: result.message,
              route: result.route
            }, null, 2)
          }]
        };
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
