#!/usr/bin/env node
/**
 * Task Copilot MCP Server
 *
 * Provides PRD and task management for Claude Code.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

import { DatabaseClient } from './database.js';
import { prdCreate, prdGet, prdList } from './tools/prd.js';
import { taskCreate, taskUpdate, taskGet, taskList } from './tools/task.js';
import { workProductStore, workProductGet, workProductList } from './tools/work-product.js';
import { initiativeLink, initiativeArchive, initiativeWipe, progressSummary } from './tools/initiative.js';
import { agentPerformanceGet } from './tools/performance.js';
import { checkpointCreate, checkpointGet, checkpointResume, checkpointList, checkpointCleanup } from './tools/checkpoint.js';
import { iterationStart, iterationValidate, iterationNext, iterationComplete } from './tools/iteration.js';
import { streamList, streamGet, streamConflictCheck, streamUnarchive, streamArchiveAll } from './tools/stream.js';
import {
  evaluateStopHooks,
  createDefaultHook,
  createValidationHook,
  createPromiseHook,
  getTaskHooks,
  clearTaskHooks
} from './tools/stop-hooks.js';
import { sessionGuard } from './tools/session-guard.js';
import { agentHandoff, agentChainGet } from './tools/agent-handoff.js';
import { preflightCheck } from './tools/preflight.js';
import { worktreeConflictStatus, worktreeConflictResolve } from './tools/worktree.js';
import { scopeChangeRequest, scopeChangeReview, scopeChangeList } from './tools/scope-change.js';
import { getValidator, initValidator } from './validation/index.js';
import { createHttpServer } from './http-server.js';
import type {
  PrdCreateInput,
  PrdGetInput,
  PrdListInput,
  TaskCreateInput,
  TaskUpdateInput,
  TaskGetInput,
  TaskListInput,
  WorkProductStoreInput,
  WorkProductGetInput,
  WorkProductListInput,
  InitiativeLinkInput,
  InitiativeArchiveInput,
  InitiativeWipeInput,
  ProgressSummaryInput,
  AgentPerformanceGetInput,
  CheckpointCreateInput,
  CheckpointGetInput,
  CheckpointResumeInput,
  CheckpointListInput,
  CheckpointCleanupInput,
  ValidationRulesListInput,
  SessionGuardInput,
  AgentHandoffInput,
  AgentChainGetInput,
  StreamListInput,
  StreamGetInput,
  StreamConflictCheckInput,
  StreamUnarchiveInput,
  StreamArchiveAllInput,
  PreflightCheckInput,
  ScopeChangeRequestInput,
  ScopeChangeReviewInput,
  ScopeChangeListInput,
  TaskStatus,
  PrdStatus,
  WorkProductType,
  IterationConfig
} from './types.js';
import type {
  IterationStartInput,
  IterationValidateInput,
  IterationNextInput,
  IterationCompleteInput
} from './tools/iteration.js';

// Get configuration from environment
const PROJECT_PATH = process.cwd();
const TASK_DB_PATH = process.env.TASK_DB_PATH || undefined;
const WORKSPACE_ID = process.env.WORKSPACE_ID || undefined;
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';
const HTTP_API_HOST = process.env.HTTP_API_HOST || '127.0.0.1';
const HTTP_API_PORT = parseInt(process.env.HTTP_API_PORT || '9090', 10);

// Initialize database
const db = new DatabaseClient(PROJECT_PATH, TASK_DB_PATH, WORKSPACE_ID);

// Create MCP server
const server = new Server(
  {
    name: 'task-copilot',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Tool definitions
const TOOLS = [
  {
    name: 'prd_create',
    description: 'Create a new PRD',
    inputSchema: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'PRD title' },
        description: { type: 'string', description: 'PRD description' },
        content: { type: 'string', description: 'Full PRD content' },
        metadata: {
          type: 'object',
          description: 'Optional metadata (priority, complexity, tags, etc.)',
          properties: {
            priority: { type: 'string' },
            complexity: { type: 'string' },
            tags: { type: 'array', items: { type: 'string' } }
          }
        }
      },
      required: ['title', 'content']
    }
  },
  {
    name: 'prd_get',
    description: 'Get PRD by ID',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'PRD ID' },
        includeContent: { type: 'boolean', description: 'Include full content (default false)' }
      },
      required: ['id']
    }
  },
  {
    name: 'prd_list',
    description: 'List PRDs for initiative',
    inputSchema: {
      type: 'object',
      properties: {
        initiativeId: { type: 'string', description: 'Filter by initiative ID' },
        status: {
          type: 'string',
          enum: ['active', 'archived', 'cancelled'],
          description: 'Filter by status'
        }
      }
    }
  },
  {
    name: 'task_create',
    description: 'Create task or subtask',
    inputSchema: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'Task title' },
        description: { type: 'string', description: 'Task description' },
        prdId: { type: 'string', description: 'Parent PRD ID (optional)' },
        parentId: { type: 'string', description: 'Parent task ID for subtasks (optional)' },
        assignedAgent: { type: 'string', description: 'Assigned agent name' },
        metadata: {
          type: 'object',
          description: 'Optional metadata (complexity, priority, dependencies, acceptanceCriteria, phase)',
          properties: {
            complexity: { type: 'string' },
            priority: { type: 'string' },
            dependencies: { type: 'array', items: { type: 'string' } },
            acceptanceCriteria: { type: 'array', items: { type: 'string' } },
            phase: { type: 'string' }
          }
        }
      },
      required: ['title']
    }
  },
  {
    name: 'task_update',
    description: 'Update task',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Task ID' },
        status: {
          type: 'string',
          enum: ['pending', 'in_progress', 'blocked', 'completed', 'cancelled'],
          description: 'New status'
        },
        assignedAgent: { type: 'string', description: 'New assigned agent' },
        notes: { type: 'string', description: 'Task notes' },
        blockedReason: { type: 'string', description: 'Reason if blocked' },
        metadata: { type: 'object', description: 'Metadata updates (merged)' }
      },
      required: ['id']
    }
  },
  {
    name: 'task_get',
    description: 'Get task details',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Task ID' },
        includeSubtasks: { type: 'boolean', description: 'Include subtasks (default false)' },
        includeWorkProducts: { type: 'boolean', description: 'Include work products (default false)' }
      },
      required: ['id']
    }
  },
  {
    name: 'task_list',
    description: 'List tasks with filters',
    inputSchema: {
      type: 'object',
      properties: {
        prdId: { type: 'string', description: 'Filter by PRD ID' },
        parentId: { type: 'string', description: 'Filter by parent task ID (null for top-level)' },
        status: {
          type: 'string',
          enum: ['pending', 'in_progress', 'blocked', 'completed', 'cancelled'],
          description: 'Filter by status'
        },
        assignedAgent: { type: 'string', description: 'Filter by assigned agent' }
      }
    }
  },
  {
    name: 'work_product_store',
    description: 'Store agent output',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID' },
        type: {
          type: 'string',
          enum: ['technical_design', 'implementation', 'test_plan', 'security_review', 'documentation', 'architecture', 'other'],
          description: 'Work product type'
        },
        title: { type: 'string', description: 'Work product title' },
        content: { type: 'string', description: 'Full content' },
        metadata: { type: 'object', description: 'Optional metadata' }
      },
      required: ['taskId', 'type', 'title', 'content']
    }
  },
  {
    name: 'work_product_get',
    description: 'Get full work product',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Work product ID' }
      },
      required: ['id']
    }
  },
  {
    name: 'work_product_list',
    description: 'List work products for task',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID' }
      },
      required: ['taskId']
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
    name: 'initiative_link',
    description: 'Link current initiative from Memory Copilot to Task Copilot workspace',
    inputSchema: {
      type: 'object',
      properties: {
        initiativeId: { type: 'string', description: 'Initiative ID from Memory Copilot' },
        title: { type: 'string', description: 'Initiative title' },
        description: { type: 'string', description: 'Initiative description (optional)' }
      },
      required: ['initiativeId', 'title']
    }
  },
  {
    name: 'initiative_archive',
    description: 'Archive all task data for an initiative to a JSON file',
    inputSchema: {
      type: 'object',
      properties: {
        initiativeId: { type: 'string', description: 'Initiative ID (default: current initiative)' },
        archivePath: { type: 'string', description: 'Custom archive file path (default: ~/.claude/archives/{id}_{timestamp}.json)' }
      }
    }
  },
  {
    name: 'initiative_wipe',
    description: 'Delete all task data for an initiative (fresh start)',
    inputSchema: {
      type: 'object',
      properties: {
        initiativeId: { type: 'string', description: 'Initiative ID (default: current initiative)' },
        confirm: { type: 'boolean', description: 'Safety flag - must be true to proceed' }
      },
      required: ['confirm']
    }
  },
  {
    name: 'progress_summary',
    description: 'Get high-level progress summary for initiative',
    inputSchema: {
      type: 'object',
      properties: {
        initiativeId: { type: 'string', description: 'Initiative ID (default: current initiative)' }
      }
    }
  },
  // Agent Performance Tracking
  {
    name: 'agent_performance_get',
    description: 'Get agent performance metrics (success rates, completion rates by task type)',
    inputSchema: {
      type: 'object',
      properties: {
        agentId: { type: 'string', description: 'Filter by agent ID (me, ta, qa, sec, doc, do, sd, uxd, uids, uid, cw)' },
        workProductType: {
          type: 'string',
          enum: ['technical_design', 'implementation', 'test_plan', 'security_review', 'documentation', 'architecture', 'other'],
          description: 'Filter by work product type'
        },
        complexity: { type: 'string', description: 'Filter by complexity (low, medium, high, very_high)' },
        sinceDays: { type: 'number', description: 'Only include last N days (default: all)' }
      }
    }
  },
  // Checkpoint Tools
  {
    name: 'checkpoint_create',
    description: 'Create a checkpoint for mid-task recovery. Use before risky operations or after completing significant steps. Supports Ralph Wiggum iteration metadata.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to checkpoint' },
        trigger: {
          type: 'string',
          enum: ['auto_status', 'auto_subtask', 'manual', 'error'],
          description: 'Checkpoint trigger type (default: manual)'
        },
        executionPhase: { type: 'string', description: 'Current phase (e.g., analysis, implementation)' },
        executionStep: { type: 'number', description: 'Step number within phase' },
        agentContext: { type: 'object', description: 'Agent-specific state to preserve' },
        draftContent: { type: 'string', description: 'Partial work in progress' },
        draftType: {
          type: 'string',
          enum: ['technical_design', 'implementation', 'test_plan', 'security_review', 'documentation', 'architecture', 'other'],
          description: 'Type of draft content'
        },
        expiresIn: { type: 'number', description: 'Minutes until checkpoint expires (default: 1440 = 24h)' },
        iterationConfig: {
          type: 'object',
          description: 'Ralph Wiggum iteration configuration (maxIterations, completionPromises, validationRules, circuitBreakerThreshold)',
          properties: {
            maxIterations: { type: 'number', description: 'Maximum number of iterations allowed' },
            completionPromises: { type: 'array', items: { type: 'string' }, description: 'List of completion criteria' },
            validationRules: {
              type: 'array',
              description: 'Validation rules to apply',
              items: {
                type: 'object',
                properties: {
                  type: { type: 'string' },
                  config: { type: 'object' }
                }
              }
            },
            circuitBreakerThreshold: { type: 'number', description: 'Consecutive failures before breaking (default: 3)' }
          },
          required: ['maxIterations', 'completionPromises']
        },
        iterationNumber: { type: 'number', description: 'Current iteration number (default: 0)' }
      },
      required: ['taskId']
    }
  },
  {
    name: 'checkpoint_get',
    description: 'Get a specific checkpoint by ID with full details',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Checkpoint ID' }
      },
      required: ['id']
    }
  },
  {
    name: 'checkpoint_resume',
    description: 'Resume task from last checkpoint. Returns state and context for continuing work, including Ralph Wiggum iteration state (iterationConfig, iterationNumber, iterationHistory, completionPromises, validationState).',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to resume' },
        checkpointId: { type: 'string', description: 'Specific checkpoint ID (default: latest)' }
      },
      required: ['taskId']
    }
  },
  {
    name: 'checkpoint_list',
    description: 'List available checkpoints for a task',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID' },
        limit: { type: 'number', description: 'Max results (default: 5)' },
        iterationNumber: { type: 'number', description: 'Filter by iteration number' },
        hasIteration: { type: 'boolean', description: 'Filter checkpoints that have (true) or don\'t have (false) iteration data' }
      },
      required: ['taskId']
    }
  },
  {
    name: 'checkpoint_cleanup',
    description: 'Clean up old or expired checkpoints',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Clean specific task (omit for all)' },
        olderThan: { type: 'number', description: 'Remove checkpoints older than N minutes' },
        keepLatest: { type: 'number', description: 'Keep N most recent per task (default: 3)' }
      }
    }
  },
  // Validation Tools
  {
    name: 'validation_config_get',
    description: 'Get current validation configuration',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'validation_rules_list',
    description: 'List validation rules for a work product type',
    inputSchema: {
      type: 'object',
      properties: {
        type: {
          type: 'string',
          enum: ['technical_design', 'implementation', 'test_plan', 'security_review', 'documentation', 'architecture', 'other'],
          description: 'Work product type to get rules for (omit for global rules)'
        }
      }
    }
  },
  // Ralph Wiggum Iteration Tools
  {
    name: 'iteration_start',
    description: 'Initialize a new iteration loop with Ralph Wiggum pattern. Creates checkpoint with iteration_number=1 and stores iteration configuration.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to start iteration for' },
        maxIterations: { type: 'number', description: 'Maximum number of iterations allowed (must be >= 1)' },
        completionPromises: {
          type: 'array',
          items: { type: 'string' },
          description: 'List of completion criteria that must be met'
        },
        validationRules: {
          type: 'array',
          description: 'Optional validation rules to apply each iteration',
          items: {
            type: 'object',
            properties: {
              type: { type: 'string', description: 'Rule type' },
              name: { type: 'string', description: 'Rule name' },
              config: { type: 'object', description: 'Rule configuration' }
            },
            required: ['type', 'name', 'config']
          }
        },
        circuitBreakerThreshold: {
          type: 'number',
          description: 'Number of consecutive failures before circuit breaker triggers (default: 3)'
        }
      },
      required: ['taskId', 'maxIterations', 'completionPromises']
    }
  },
  {
    name: 'iteration_validate',
    description: 'Run validation rules against current iteration. Returns validation results, completion signal (CONTINUE/COMPLETE/BLOCKED/ESCALATE), and actionable feedback. Integrates safety guards to detect runaway loops.',
    inputSchema: {
      type: 'object',
      properties: {
        iterationId: { type: 'string', description: 'Iteration checkpoint ID from iteration_start' },
        agentOutput: { type: 'string', description: 'Agent output to validate for completion promises like <promise>COMPLETE</promise> or <promise>BLOCKED</promise>' }
      },
      required: ['iterationId']
    }
  },
  {
    name: 'iteration_next',
    description: 'Advance to next iteration. Increments iteration number and updates history. Throws if max iterations reached.',
    inputSchema: {
      type: 'object',
      properties: {
        iterationId: { type: 'string', description: 'Iteration checkpoint ID' },
        validationResult: { type: 'object', description: 'Validation result from iteration_validate (optional)' },
        agentContext: { type: 'object', description: 'Agent state to preserve for next iteration (optional)' }
      },
      required: ['iterationId']
    }
  },
  {
    name: 'iteration_complete',
    description: 'Mark iteration as complete. Updates task status to completed and optionally links final work product.',
    inputSchema: {
      type: 'object',
      properties: {
        iterationId: { type: 'string', description: 'Iteration checkpoint ID' },
        completionPromise: { type: 'string', description: 'Which completion promise was met' },
        workProductId: { type: 'string', description: 'Optional final work product ID' }
      },
      required: ['iterationId', 'completionPromise']
    }
  },
  // Stop Hook Tools (Phase 2)
  {
    name: 'hook_register',
    description: 'Register a stop hook for a task. Hooks intercept completion signals and decide whether to complete, continue, or escalate. Use preset hooks: "default" (validation + promises), "validation" (rules only), "promise" (promises only).',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to register hook for' },
        hookType: {
          type: 'string',
          enum: ['default', 'validation', 'promise'],
          description: 'Preset hook type: "default" (recommended), "validation", or "promise"'
        },
        metadata: { type: 'object', description: 'Optional metadata to attach to hook' }
      },
      required: ['taskId', 'hookType']
    }
  },
  {
    name: 'hook_evaluate',
    description: 'Evaluate registered hooks for an iteration. Returns action (complete/continue/escalate) and reason. Called internally by iteration_validate but can be used manually for testing.',
    inputSchema: {
      type: 'object',
      properties: {
        iterationId: { type: 'string', description: 'Iteration checkpoint ID' },
        agentOutput: { type: 'string', description: 'Agent output to analyze for completion promises' },
        filesModified: {
          type: 'array',
          items: { type: 'string' },
          description: 'List of file paths modified in this iteration (optional)'
        },
        draftContent: { type: 'string', description: 'Draft work product content (optional)' },
        draftType: {
          type: 'string',
          enum: ['technical_design', 'implementation', 'test_plan', 'security_review', 'documentation', 'architecture', 'other'],
          description: 'Draft work product type (optional)'
        }
      },
      required: ['iterationId']
    }
  },
  {
    name: 'hook_list',
    description: 'List all registered hooks for a task. Returns hook IDs, enabled status, and metadata.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to list hooks for' }
      },
      required: ['taskId']
    }
  },
  {
    name: 'hook_clear',
    description: 'Clear all hooks for a task. Should be called when iteration loop completes or is cancelled.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to clear hooks for' }
      },
      required: ['taskId']
    }
  },
  // Session Guard Tool
  {
    name: 'session_guard',
    description: 'Enforce main session guardrails to prevent context bloat. Use "check" to validate current session behavior against rules, or "report" to get a summary of guidelines and initiative status.',
    inputSchema: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['check', 'report'],
          description: 'Action to perform: "check" validates context against rules, "report" provides guidelines summary'
        },
        context: {
          type: 'object',
          description: 'Session context to check (optional for report)',
          properties: {
            filesRead: { type: 'number', description: 'Number of files read in main session' },
            codeWritten: { type: 'boolean', description: 'Whether code was written directly in main session' },
            agentUsed: { type: 'string', description: 'Name of agent invoked (if any)' },
            responseTokens: { type: 'number', description: 'Estimated response token count' }
          }
        }
      },
      required: ['action']
    }
  },
  // Agent Handoff Tools
  {
    name: 'agent_handoff',
    description: 'Record agent handoff in multi-agent collaboration chain. Intermediate agents store work in Task Copilot and pass minimal context (max 50 chars) to next agent. Only final agent returns to main session.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID' },
        fromAgent: { type: 'string', description: 'Agent handing off (sd, uxd, uids, uid, etc.)' },
        toAgent: { type: 'string', description: 'Agent receiving handoff' },
        workProductId: { type: 'string', description: 'Work product ID created by fromAgent' },
        handoffContext: { type: 'string', description: 'Brief context for next agent (max 50 chars)' },
        chainPosition: { type: 'number', description: 'Position in chain (1-based)' },
        chainLength: { type: 'number', description: 'Total agents in chain' }
      },
      required: ['taskId', 'fromAgent', 'toAgent', 'workProductId', 'handoffContext', 'chainPosition', 'chainLength']
    }
  },
  {
    name: 'agent_chain_get',
    description: 'Get full agent collaboration chain for a task. Final agent uses this to retrieve all prior work products and handoff contexts before returning consolidated summary to main session.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID' }
      },
      required: ['taskId']
    }
  },
  // Stream Tools (Command Arguments & Independent Streams)
  {
    name: 'stream_list',
    description: 'List all work streams for an initiative. Groups tasks by streamId and returns status for each stream. By default, excludes archived streams.',
    inputSchema: {
      type: 'object',
      properties: {
        initiativeId: { type: 'string', description: 'Filter by initiative ID (default: current initiative)' },
        prdId: { type: 'string', description: 'Filter by PRD ID' },
        includeArchived: { type: 'boolean', description: 'Include archived streams (default: false)' }
      }
    }
  },
  {
    name: 'stream_get',
    description: 'Get all tasks for a specific stream by streamId. Returns null if stream is archived unless includeArchived=true.',
    inputSchema: {
      type: 'object',
      properties: {
        streamId: { type: 'string', description: 'Stream ID (e.g., "Stream-A", "Stream-B")' },
        initiativeId: { type: 'string', description: 'Filter by initiative ID (optional)' },
        includeArchived: { type: 'boolean', description: 'Include archived stream (default: false)' }
      },
      required: ['streamId']
    }
  },
  {
    name: 'stream_conflict_check',
    description: 'Check if files are already being worked on by other streams. Use before starting work to detect conflicts.',
    inputSchema: {
      type: 'object',
      properties: {
        files: { type: 'array', items: { type: 'string' }, description: 'File paths to check' },
        excludeStreamId: { type: 'string', description: 'Exclude tasks from this stream (optional)' },
        initiativeId: { type: 'string', description: 'Filter by initiative ID (optional)' }
      },
      required: ['files']
    }
  },
  {
    name: 'stream_unarchive',
    description: 'Unarchive a stream and link it to current or specified initiative. Use when you want to resume work on an archived stream. Optional prdId to scope unarchive to specific PRD.',
    inputSchema: {
      type: 'object',
      properties: {
        streamId: { type: 'string', description: 'Stream ID to unarchive (e.g., "Stream-A")' },
        initiativeId: { type: 'string', description: 'Initiative ID to link stream to (default: current initiative)' },
        prdId: { type: 'string', description: 'Optional: only unarchive tasks belonging to this PRD' }
      },
      required: ['streamId']
    }
  },
  {
    name: 'stream_archive_all',
    description: 'Archive all active streams. One-time cleanup for legacy data before auto-archive feature. Requires confirm: true for safety. Optional prdId to scope archival to specific PRD.',
    inputSchema: {
      type: 'object',
      properties: {
        confirm: { type: 'boolean', description: 'Safety flag - must be true to proceed' },
        initiativeId: { type: 'string', description: 'Optional: only archive streams from specific initiative' },
        prdId: { type: 'string', description: 'Optional: only archive streams from specific PRD (takes precedence over initiativeId)' }
      },
      required: ['confirm']
    }
  },
  // Preflight Check (Session Boundary Protocol)
  {
    name: 'preflight_check',
    description: 'Check environment health before starting substantive work. Verifies initiative state, git status, optional dev server and tests. Part of Session Boundary Protocol.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Optional task ID to check preflight config from task metadata' },
        initiativeId: { type: 'string', description: 'Optional initiative ID (default: current initiative)' },
        checkDevServer: { type: 'boolean', description: 'Check if dev server is running (default: false unless task specifies)' },
        devServerPort: { type: 'number', description: 'Port to check for dev server (default: 3000)' },
        testCommand: { type: 'string', description: 'Test command to run for baseline validation (e.g., "npm test")' }
      }
    }
  },
  // Worktree Conflict Management
  {
    name: 'worktree_conflict_status',
    description: 'Check conflict status for a task worktree. Returns list of conflicting files if any exist.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to check conflict status for' }
      },
      required: ['taskId']
    }
  },
  {
    name: 'worktree_conflict_resolve',
    description: 'Retry merge after manual conflict resolution. Attempts to complete merge and mark task as completed if conflicts are resolved.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: { type: 'string', description: 'Task ID to resolve conflicts for' },
        targetBranch: { type: 'string', description: 'Target branch to merge into (optional, defaults to current)' }
      },
      required: ['taskId']
    }
  },
  // Scope Change Request Tools (P3.3)
  {
    name: 'scope_change_request',
    description: 'Request a scope change for a locked PRD. Worker agents use this when they need to add, modify, or remove tasks from a scope-locked PRD. Only @agent-ta can approve/reject.',
    inputSchema: {
      type: 'object',
      properties: {
        prdId: { type: 'string', description: 'PRD ID to request change for' },
        requestType: {
          type: 'string',
          enum: ['add_task', 'modify_task', 'remove_task'],
          description: 'Type of scope change requested'
        },
        description: { type: 'string', description: 'What change is requested (detailed description)' },
        rationale: { type: 'string', description: 'Why this change is needed (justification)' },
        requestedBy: { type: 'string', description: 'Agent making the request (e.g., "me", "qa", "doc")' }
      },
      required: ['prdId', 'requestType', 'description', 'rationale', 'requestedBy']
    }
  },
  {
    name: 'scope_change_review',
    description: 'Review and approve/reject a scope change request. Typically used by @agent-ta or user to approve/reject requests from worker agents.',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'Scope change request ID' },
        status: {
          type: 'string',
          enum: ['approved', 'rejected'],
          description: 'Decision on the request'
        },
        reviewNotes: { type: 'string', description: 'Optional notes explaining the decision' },
        reviewedBy: { type: 'string', description: 'Who reviewed (e.g., "ta", "user")' }
      },
      required: ['id', 'status']
    }
  },
  {
    name: 'scope_change_list',
    description: 'List scope change requests. Filter by PRD or status (pending, approved, rejected).',
    inputSchema: {
      type: 'object',
      properties: {
        prdId: { type: 'string', description: 'Filter by PRD ID (optional)' },
        status: {
          type: 'string',
          enum: ['pending', 'approved', 'rejected'],
          description: 'Filter by status (optional)'
        }
      }
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
      case 'prd_create': {
        const result = await prdCreate(db, {
          title: a.title as string,
          description: a.description as string | undefined,
          content: a.content as string,
          metadata: a.metadata as Record<string, unknown> | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'prd_get': {
        const result = prdGet(db, {
          id: a.id as string,
          includeContent: a.includeContent as boolean | undefined
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'PRD not found' }] };
      }

      case 'prd_list': {
        const result = prdList(db, {
          initiativeId: a.initiativeId as string | undefined,
          status: a.status as PrdStatus | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'task_create': {
        const result = await taskCreate(db, {
          title: a.title as string,
          description: a.description as string | undefined,
          prdId: a.prdId as string | undefined,
          parentId: a.parentId as string | undefined,
          assignedAgent: a.assignedAgent as string | undefined,
          metadata: a.metadata as Record<string, unknown> | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'task_update': {
        const result = await taskUpdate(db, {
          id: a.id as string,
          status: a.status as TaskStatus | undefined,
          assignedAgent: a.assignedAgent as string | undefined,
          notes: a.notes as string | undefined,
          blockedReason: a.blockedReason as string | undefined,
          metadata: a.metadata as Record<string, unknown> | undefined
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'Task not found' }] };
      }

      case 'task_get': {
        const result = taskGet(db, {
          id: a.id as string,
          includeSubtasks: a.includeSubtasks as boolean | undefined,
          includeWorkProducts: a.includeWorkProducts as boolean | undefined
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'Task not found' }] };
      }

      case 'task_list': {
        const result = taskList(db, {
          prdId: a.prdId as string | undefined,
          parentId: a.parentId as string | undefined,
          status: a.status as TaskStatus | undefined,
          assignedAgent: a.assignedAgent as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'work_product_store': {
        const result = await workProductStore(db, {
          taskId: a.taskId as string,
          type: a.type as WorkProductType,
          title: a.title as string,
          content: a.content as string,
          metadata: a.metadata as Record<string, unknown> | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'work_product_get': {
        const result = workProductGet(db, {
          id: a.id as string
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'Work product not found' }] };
      }

      case 'work_product_list': {
        const result = workProductList(db, {
          taskId: a.taskId as string
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'health_check': {
        const stats = db.getStats();
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              status: 'healthy',
              workspaceId: db.getWorkspaceId(),
              ...stats
            })
          }]
        };
      }

      case 'initiative_link': {
        const result = initiativeLink(db, {
          initiativeId: a.initiativeId as string,
          title: a.title as string,
          description: a.description as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'initiative_archive': {
        const result = initiativeArchive(db, {
          initiativeId: a.initiativeId as string | undefined,
          archivePath: a.archivePath as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'initiative_wipe': {
        const result = initiativeWipe(db, {
          initiativeId: a.initiativeId as string | undefined,
          confirm: a.confirm as boolean
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'progress_summary': {
        const result = progressSummary(db, {
          initiativeId: a.initiativeId as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Agent Performance Tracking
      case 'agent_performance_get': {
        const result = agentPerformanceGet(db, {
          agentId: a.agentId as string | undefined,
          workProductType: a.workProductType as string | undefined,
          complexity: a.complexity as string | undefined,
          sinceDays: a.sinceDays as number | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Checkpoint Tools
      case 'checkpoint_create': {
        const result = checkpointCreate(db, {
          taskId: a.taskId as string,
          trigger: a.trigger as 'auto_status' | 'auto_subtask' | 'manual' | 'error' | undefined,
          executionPhase: a.executionPhase as string | undefined,
          executionStep: a.executionStep as number | undefined,
          agentContext: a.agentContext as Record<string, unknown> | undefined,
          draftContent: a.draftContent as string | undefined,
          draftType: a.draftType as WorkProductType | undefined,
          expiresIn: a.expiresIn as number | undefined,
          iterationConfig: a.iterationConfig as IterationConfig | undefined,
          iterationNumber: a.iterationNumber as number | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'checkpoint_get': {
        const result = checkpointGet(db, {
          id: a.id as string
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'Checkpoint not found' }] };
      }

      case 'checkpoint_resume': {
        const result = checkpointResume(db, {
          taskId: a.taskId as string,
          checkpointId: a.checkpointId as string | undefined
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'No checkpoint found' }] };
      }

      case 'checkpoint_list': {
        const result = checkpointList(db, {
          taskId: a.taskId as string,
          limit: a.limit as number | undefined,
          iterationNumber: a.iterationNumber as number | undefined,
          hasIteration: a.hasIteration as boolean | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'checkpoint_cleanup': {
        const result = checkpointCleanup(db, {
          taskId: a.taskId as string | undefined,
          olderThan: a.olderThan as number | undefined,
          keepLatest: a.keepLatest as number | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Validation Tools
      case 'validation_config_get': {
        const validator = getValidator();
        const config = validator.getConfig();
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              version: config.version,
              defaultMode: config.defaultMode,
              globalRulesCount: config.globalRules.length,
              typeRules: Object.fromEntries(
                Object.entries(config.typeRules).map(([k, v]) => [k, v.length])
              )
            })
          }]
        };
      }

      case 'validation_rules_list': {
        const validator = getValidator();
        const type = a.type as WorkProductType | undefined;
        const rules = validator.getRulesForType(type || 'global');
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              type: type || 'global',
              rules: rules.map(r => ({
                id: r.id,
                name: r.name,
                description: r.description,
                type: r.type,
                severity: r.severity,
                enabled: r.enabled
              }))
            })
          }]
        };
      }

      // Ralph Wiggum Iteration Tools
      case 'iteration_start': {
        const result = iterationStart(db, {
          taskId: a.taskId as string,
          maxIterations: a.maxIterations as number,
          completionPromises: a.completionPromises as string[],
          validationRules: a.validationRules as Array<{
            type: string;
            name: string;
            config: Record<string, unknown>;
          }> | undefined,
          circuitBreakerThreshold: a.circuitBreakerThreshold as number | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'iteration_validate': {
        const result = await iterationValidate(db, {
          iterationId: a.iterationId as string,
          agentOutput: a.agentOutput as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'iteration_next': {
        const result = iterationNext(db, {
          iterationId: a.iterationId as string,
          validationResult: a.validationResult as object | undefined,
          agentContext: a.agentContext as object | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'iteration_complete': {
        const result = iterationComplete(db, {
          iterationId: a.iterationId as string,
          completionPromise: a.completionPromise as string,
          workProductId: a.workProductId as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Stop Hook Tools (Phase 2)
      case 'hook_register': {
        const taskId = a.taskId as string;
        const hookType = a.hookType as string;
        const metadata = a.metadata as Record<string, unknown> | undefined;

        let hookId: string;
        switch (hookType) {
          case 'default':
            hookId = createDefaultHook(taskId);
            break;
          case 'validation':
            hookId = createValidationHook(taskId);
            break;
          case 'promise':
            hookId = createPromiseHook(taskId);
            break;
          default:
            throw new Error(`Unknown hook type: ${hookType}`);
        }

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              hookId,
              taskId,
              hookType,
              enabled: true,
              metadata
            })
          }]
        };
      }

      case 'hook_evaluate': {
        const result = await evaluateStopHooks(db, {
          iterationId: a.iterationId as string,
          agentOutput: a.agentOutput as string | undefined,
          filesModified: a.filesModified as string[] | undefined,
          draftContent: a.draftContent as string | undefined,
          draftType: a.draftType as WorkProductType | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'hook_list': {
        const taskId = a.taskId as string;
        const hooks = getTaskHooks(taskId);

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              taskId,
              hookCount: hooks.length,
              hooks: hooks.map(h => ({
                id: h.id,
                enabled: h.enabled,
                metadata: h.metadata
              }))
            })
          }]
        };
      }

      case 'hook_clear': {
        const taskId = a.taskId as string;
        const cleared = clearTaskHooks(taskId);

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              taskId,
              hooksCleared: cleared
            })
          }]
        };
      }

      // Session Guard Tool
      case 'session_guard': {
        const result = sessionGuard(db, {
          action: a.action as 'check' | 'report',
          context: a.context as SessionGuardInput['context'] | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Agent Handoff Tools
      case 'agent_handoff': {
        const result = agentHandoff(db, {
          taskId: a.taskId as string,
          fromAgent: a.fromAgent as string,
          toAgent: a.toAgent as string,
          workProductId: a.workProductId as string,
          handoffContext: a.handoffContext as string,
          chainPosition: a.chainPosition as number,
          chainLength: a.chainLength as number
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'agent_chain_get': {
        const result = agentChainGet(db, {
          taskId: a.taskId as string
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'Task not found' }] };
      }

      // Stream Tools
      case 'stream_list': {
        const result = streamList(db, {
          initiativeId: a.initiativeId as string | undefined,
          prdId: a.prdId as string | undefined,
          includeArchived: a.includeArchived as boolean | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'stream_get': {
        const result = streamGet(db, {
          streamId: a.streamId as string,
          initiativeId: a.initiativeId as string | undefined,
          includeArchived: a.includeArchived as boolean | undefined
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'Stream not found' }] };
      }

      case 'stream_conflict_check': {
        const result = streamConflictCheck(db, {
          files: a.files as string[],
          excludeStreamId: a.excludeStreamId as string | undefined,
          initiativeId: a.initiativeId as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'stream_unarchive': {
        const result = streamUnarchive(db, {
          streamId: a.streamId as string,
          initiativeId: a.initiativeId as string | undefined,
          prdId: a.prdId as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'stream_archive_all': {
        const result = streamArchiveAll(db, {
          confirm: a.confirm as boolean,
          initiativeId: a.initiativeId as string | undefined,
          prdId: a.prdId as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Preflight Check
      case 'preflight_check': {
        const result = await preflightCheck(db, {
          taskId: a.taskId as string | undefined,
          initiativeId: a.initiativeId as string | undefined,
          checkDevServer: a.checkDevServer as boolean | undefined,
          devServerPort: a.devServerPort as number | undefined,
          testCommand: a.testCommand as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Worktree Conflict Management
      case 'worktree_conflict_status': {
        const result = await worktreeConflictStatus(db, {
          taskId: a.taskId as string
        });
        return { content: [{ type: 'text', text: result ? JSON.stringify(result) : 'Task not found' }] };
      }

      case 'worktree_conflict_resolve': {
        const result = await worktreeConflictResolve(db, {
          taskId: a.taskId as string,
          targetBranch: a.targetBranch as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      // Scope Change Request Tools (P3.3)
      case 'scope_change_request': {
        const result = scopeChangeRequest(db, {
          prdId: a.prdId as string,
          requestType: a.requestType as 'add_task' | 'modify_task' | 'remove_task',
          description: a.description as string,
          rationale: a.rationale as string,
          requestedBy: a.requestedBy as string
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'scope_change_review': {
        const result = scopeChangeReview(db, {
          id: a.id as string,
          status: a.status as 'approved' | 'rejected',
          reviewNotes: a.reviewNotes as string | undefined,
          reviewedBy: a.reviewedBy as string | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      case 'scope_change_list': {
        const result = scopeChangeList(db, {
          prdId: a.prdId as string | undefined,
          status: a.status as 'pending' | 'approved' | 'rejected' | undefined
        });
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      }

      default:
        return { content: [{ type: 'text', text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return { content: [{ type: 'text', text: `Error: ${message}` }], isError: true };
  }
});

// Start server
async function main() {
  if (LOG_LEVEL === 'debug') {
    console.error('Task Copilot server starting...');
    console.error(`Project: ${PROJECT_PATH}`);
    console.error(`Workspace ID: ${WORKSPACE_ID || '(auto-generated)'}`);
    console.error(`Workspace ID (actual): ${db.getWorkspaceId()}`);
  }

  // Initialize validation system
  initValidator();

  // Clean up expired checkpoints on startup
  const expiredCount = db.deleteExpiredCheckpoints();
  if (expiredCount > 0 && LOG_LEVEL === 'debug') {
    console.error(`Cleaned up ${expiredCount} expired checkpoints`);
  }

  // Start MCP server
  const transport = new StdioServerTransport();
  await server.connect(transport);

  if (LOG_LEVEL === 'debug') {
    console.error('Task Copilot server running');
  }

  // Start HTTP API server
  try {
    await createHttpServer({
      host: HTTP_API_HOST,
      port: HTTP_API_PORT,
      db
    });
  } catch (error) {
    console.error('Failed to start HTTP API server:', error);
    // Don't fail if HTTP server fails - MCP server should still work
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
