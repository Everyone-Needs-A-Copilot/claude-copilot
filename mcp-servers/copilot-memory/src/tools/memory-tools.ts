/**
 * MCP tools for memory operations
 */

import { v4 as uuidv4 } from 'uuid';
import type { DatabaseClient } from '../db/client.js';
import { generateEmbedding } from '../embeddings/generator.js';
import type {
  Memory,
  MemoryRow,
  MemorySearchResult,
  MemoryStoreInput,
  MemoryUpdateInput,
  MemoryListInput,
  MemorySearchInput,
  MemoryType,
  AgentImprovementMetadata
} from '../types.js';

/**
 * Validate agent_improvement metadata
 */
function validateAgentImprovementMetadata(metadata: Record<string, unknown>): void {
  const requiredFields: (keyof AgentImprovementMetadata)[] = [
    'agentId',
    'targetSection',
    'currentContent',
    'suggestedContent',
    'rationale',
    'status'
  ];

  for (const field of requiredFields) {
    if (!(field in metadata)) {
      throw new Error(`agent_improvement type requires metadata field: ${field}`);
    }
  }

  // Validate status enum
  const status = metadata.status;
  if (status !== 'pending' && status !== 'approved' && status !== 'rejected') {
    throw new Error(`agent_improvement metadata.status must be 'pending', 'approved', or 'rejected', got: ${status}`);
  }

  // Validate string fields
  const stringFields: (keyof AgentImprovementMetadata)[] = [
    'agentId',
    'targetSection',
    'currentContent',
    'suggestedContent',
    'rationale'
  ];

  for (const field of stringFields) {
    if (typeof metadata[field] !== 'string' || (metadata[field] as string).trim() === '') {
      throw new Error(`agent_improvement metadata.${field} must be a non-empty string`);
    }
  }
}

/**
 * Convert database row to Memory object
 */
function rowToMemory(row: MemoryRow): Memory {
  return {
    id: row.id,
    projectId: row.project_id,
    content: row.content,
    type: row.type as MemoryType,
    tags: JSON.parse(row.tags),
    metadata: JSON.parse(row.metadata),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    sessionId: row.session_id || undefined
  };
}

/**
 * Store a new memory with auto-embedding
 */
export async function memoryStore(
  db: DatabaseClient,
  input: MemoryStoreInput,
  sessionId?: string
): Promise<Memory> {
  // Validate agent_improvement metadata if applicable
  if (input.type === 'agent_improvement') {
    if (!input.metadata) {
      throw new Error('agent_improvement type requires metadata');
    }
    validateAgentImprovementMetadata(input.metadata);
  }

  const id = uuidv4();
  const now = new Date().toISOString();

  const row: Omit<MemoryRow, 'project_id'> = {
    id,
    content: input.content,
    type: input.type,
    tags: JSON.stringify(input.tags || []),
    metadata: JSON.stringify(input.metadata || {}),
    created_at: now,
    updated_at: now,
    session_id: sessionId || null
  };

  // Store in database
  db.insertMemory(row);

  // Generate and store embedding
  const embedding = await generateEmbedding(input.content);
  db.insertEmbedding(id, embedding);

  return rowToMemory({
    ...row,
    project_id: db.getProjectId()
  });
}

/**
 * Update an existing memory
 */
export async function memoryUpdate(
  db: DatabaseClient,
  input: MemoryUpdateInput
): Promise<Memory | null> {
  const existing = db.getMemory(input.id);
  if (!existing) {
    return null;
  }

  const updates: Partial<MemoryRow> = {};

  if (input.content !== undefined) {
    updates.content = input.content;

    // Regenerate embedding
    db.deleteEmbedding(input.id);
    const embedding = await generateEmbedding(input.content);
    db.insertEmbedding(input.id, embedding);
  }

  if (input.tags !== undefined) {
    updates.tags = JSON.stringify(input.tags);
  }

  if (input.metadata !== undefined) {
    updates.metadata = JSON.stringify(input.metadata);
  }

  db.updateMemory(input.id, updates);

  const updated = db.getMemory(input.id);
  return updated ? rowToMemory(updated) : null;
}

/**
 * Delete a memory
 */
export function memoryDelete(db: DatabaseClient, id: string): boolean {
  const existing = db.getMemory(id);
  if (!existing) {
    return false;
  }

  db.deleteEmbedding(id);
  db.deleteMemory(id);
  return true;
}

/**
 * Get a memory by ID
 */
export function memoryGet(db: DatabaseClient, id: string): Memory | null {
  const row = db.getMemory(id);
  return row ? rowToMemory(row) : null;
}

/**
 * List memories with optional filters
 */
export function memoryList(db: DatabaseClient, input: MemoryListInput): Memory[] {
  const rows = db.listMemories({
    type: input.type,
    tags: input.tags,
    agentId: input.agentId,
    limit: input.limit || 20,
    offset: input.offset || 0
  });

  return rows.map(rowToMemory);
}

/**
 * Semantic search across memories
 */
export async function memorySearch(
  db: DatabaseClient,
  input: MemorySearchInput
): Promise<MemorySearchResult[]> {
  // Generate query embedding
  const queryEmbedding = await generateEmbedding(input.query);

  // Search in database
  const results = db.searchByEmbedding(queryEmbedding, {
    type: input.type,
    agentId: input.agentId,
    limit: input.limit || 10,
    threshold: input.threshold || 0.7
  });

  return results.map(row => ({
    ...rowToMemory(row),
    distance: row.distance
  }));
}

/**
 * Full-text search (for exact matches)
 */
export function memoryFullTextSearch(db: DatabaseClient, query: string, limit: number = 10): Memory[] {
  const rows = db.searchFullText(query, limit);
  return rows.map(rowToMemory);
}
