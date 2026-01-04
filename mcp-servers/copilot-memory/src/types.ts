/**
 * Type definitions for the Copilot Memory MCP Server
 */

// Memory types
export type MemoryType = 'decision' | 'lesson' | 'discussion' | 'file' | 'initiative' | 'context' | 'agent_improvement';

export type InitiativeStatus = 'NOT STARTED' | 'IN PROGRESS' | 'BLOCKED' | 'READY FOR REVIEW' | 'COMPLETE';

// Memory record
export interface Memory {
  id: string;
  projectId: string;
  content: string;
  type: MemoryType;
  tags: string[];
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  sessionId?: string;
}

// Memory with search distance
export interface MemorySearchResult extends Memory {
  distance: number;
}

// Initiative record
export interface Initiative {
  id: string;
  projectId: string;
  name: string;
  goal?: string;
  status: InitiativeStatus;

  // NEW: Task Copilot integration (slim mode)
  taskCopilotLinked?: boolean;
  activePrdIds?: string[];

  // KEEP: Permanent knowledge (decisions, lessons, keyFiles)
  decisions: string[];
  lessons: string[];
  keyFiles: string[];

  // NEW: Slim resume context (replaces resumeInstructions)
  currentFocus?: string;   // Max 100 chars
  nextAction?: string;     // Max 100 chars

  // DEPRECATED: Use Task Copilot instead (kept for backward compatibility)
  completed: string[];
  inProgress: string[];
  blocked: string[];
  resumeInstructions?: string;

  createdAt: string;
  updatedAt: string;
}

// Session record
export interface Session {
  id: string;
  projectId: string;
  startedAt: string;
  endedAt?: string;
  summary?: string;
}

// Agent improvement metadata structure
export interface AgentImprovementMetadata {
  agentId: string;
  targetSection: string;
  currentContent: string;
  suggestedContent: string;
  rationale: string;
  status: 'pending' | 'approved' | 'rejected';
}

// Tool input schemas
export interface MemoryStoreInput {
  content: string;
  type: MemoryType;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export interface MemoryUpdateInput {
  id: string;
  content?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export interface MemoryListInput {
  type?: MemoryType;
  tags?: string[];
  agentId?: string;  // Filter by agentId in metadata (for agent_improvement type)
  limit?: number;
  offset?: number;
}

export interface MemorySearchInput {
  query: string;
  type?: MemoryType;
  agentId?: string;  // Filter by agentId in metadata (for agent_improvement type)
  limit?: number;
  threshold?: number;
}

export interface InitiativeStartInput {
  name: string;
  goal?: string;
  status?: InitiativeStatus;
}

export interface InitiativeUpdateInput {
  // NEW: Task Copilot integration
  taskCopilotLinked?: boolean;
  activePrdIds?: string[];

  // KEEP: Permanent knowledge
  decisions?: string[];
  lessons?: string[];
  keyFiles?: string[];

  // NEW: Slim resume context
  currentFocus?: string;
  nextAction?: string;

  // DEPRECATED but supported for backward compatibility
  completed?: string[];
  inProgress?: string[];
  blocked?: string[];
  resumeInstructions?: string;

  status?: InitiativeStatus;
}

export interface InitiativeGetInput {
  mode?: 'lean' | 'full';  // lean: ~150 tokens, full: ~370 tokens (default: lean)
}

export interface InitiativeSlimInput {
  archiveDetails?: boolean;  // Save old data to file before slimming (default: true)
}

export interface InitiativeSlimOutput {
  initiativeId: string;
  archived: boolean;
  archivePath?: string;
  removedFields: string[];
  beforeSize: number;    // Approximate token count
  afterSize: number;     // Approximate token count
  savings: string;       // "75% reduction"
}

// Database row types (snake_case for SQLite)
export interface MemoryRow {
  id: string;
  project_id: string;
  content: string;
  type: string;
  tags: string;
  metadata: string;
  created_at: string;
  updated_at: string;
  session_id: string | null;
}

export interface InitiativeRow {
  id: string;
  project_id: string;
  name: string;
  goal: string | null;
  status: string;

  // NEW: Task Copilot integration
  task_copilot_linked: number;  // SQLite boolean (0/1)
  active_prd_ids: string;       // JSON array

  // KEEP: Permanent knowledge
  decisions: string;
  lessons: string;
  key_files: string;

  // NEW: Slim resume context
  current_focus: string | null;
  next_action: string | null;

  // DEPRECATED but kept for backward compatibility
  completed: string;
  in_progress: string;
  blocked: string;
  resume_instructions: string | null;

  created_at: string;
  updated_at: string;
}

// Embedding vector
export type EmbeddingVector = Float32Array;

// Configuration
export interface ServerConfig {
  memoryPath: string;
  embeddingProvider: 'local' | 'voyage' | 'openai';
  embeddingApiKey?: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
}
