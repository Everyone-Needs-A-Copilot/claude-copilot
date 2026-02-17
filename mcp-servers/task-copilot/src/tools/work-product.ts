/**
 * Work Product tool implementations
 */

import { v4 as uuidv4 } from 'uuid';
import type { DatabaseClient } from '../database.js';
import type {
  WorkProductStoreInput,
  WorkProductGetInput,
  WorkProductListInput,
  WorkProductRow,
  ValidationResult,
} from '../types.js';
import { getValidator } from '../validation/index.js';
import { estimateTokensFromText, getStreamTokenBudget, getStreamTokenUsage } from '../utils/stream-tokens.js';

export interface WorkProductStoreResult {
  id: string;
  taskId: string;
  summary: string;
  wordCount: number;
  createdAt: string;
  validation?: {
    valid: boolean;
    flagCount: number;
    warnings: string[];
    rejected: boolean;
    feedback?: string;
  };
}

export async function workProductStore(
  db: DatabaseClient,
  input: WorkProductStoreInput
): Promise<WorkProductStoreResult> {
  const now = new Date().toISOString();
  const id = `WP-${uuidv4()}`;

  // Validate confidence if provided
  if (input.confidence !== undefined) {
    if (input.confidence < 0 || input.confidence > 1) {
      throw new Error('Confidence must be between 0 and 1');
    }
  }

  // Run validation
  const validator = getValidator();
  const task = db.getTask(input.taskId);
  const validationResult = validator.validate(
    input.content,
    input.type,
    task?.assigned_agent || undefined
  );

  // Handle rejection (if any rules have severity: 'reject')
  if (validationResult.rejected) {
    throw new Error(
      `Work product rejected by validation:\n${validationResult.actionableFeedback}`
    );
  }

  // Prepare metadata with validation flags if any warnings
  const baseMetadata = input.metadata || {};
  const metadata = validationResult.valid
    ? baseMetadata
    : {
        ...baseMetadata,
        validation: {
          flags: validationResult.flags,
          validatedAt: now,
        },
      };

  const wp: WorkProductRow = {
    id,
    task_id: input.taskId,
    type: input.type,
    title: input.title,
    content: input.content,
    metadata: JSON.stringify(metadata),
    created_at: now,
    confidence: input.confidence ?? null
  };

  // H-2: Use transaction to atomically check budget and insert work product
  // This prevents race conditions where multiple concurrent inserts could exceed budget
  if (task?.metadata) {
    const taskMetadata = typeof task.metadata === 'string'
      ? JSON.parse(task.metadata)
      : task.metadata;
    const streamId = taskMetadata.streamId as string | undefined;
    if (streamId) {
      const prd = task.prd_id ? db.getPrd(task.prd_id) : null;
      const initiativeId = prd?.initiative_id || undefined;
      const tokenBudget = getStreamTokenBudget(db, streamId, initiativeId);
      if (tokenBudget) {
        // Execute budget check and insert in a single transaction
        const transaction = db.getDb().transaction(() => {
          const currentUsage = getStreamTokenUsage(db, streamId, initiativeId);
          const contentTokens = estimateTokensFromText(input.content);
          const projectedUsage = currentUsage + contentTokens;

          if (projectedUsage > tokenBudget) {
            throw new Error(
              `Stream token budget exceeded for ${streamId}: ` +
              `${projectedUsage} > ${tokenBudget} tokens (estimated). ` +
              `Reduce work product size or raise streamTokenBudget.`
            );
          }

          db.insertWorkProduct(wp);
        });
        transaction();
      } else {
        // No budget configured, just insert
        db.insertWorkProduct(wp);
      }
    } else {
      // No stream ID, just insert
      db.insertWorkProduct(wp);
    }
  } else {
    // No task metadata, just insert
    db.insertWorkProduct(wp);
  }

  // Log activity (need initiative ID from task -> PRD)
  if (task?.prd_id) {
    const prd = db.getPrd(task.prd_id);
    if (prd) {
      const flagSuffix = validationResult.flags.length > 0
        ? ` (${validationResult.flags.length} warnings)`
        : '';
      db.insertActivity({
        id: uuidv4(),
        initiative_id: prd.initiative_id,
        type: 'work_product_created',
        entity_id: id,
        entity_type: 'work_product',
        summary: `Created ${input.type}: ${input.title}${flagSuffix}`,
        metadata: JSON.stringify({
          workProductId: id,
          taskId: input.taskId,
          type: input.type,
          title: input.title,
          wordCount: input.content.split(/\s+/).filter(w => w.length > 0).length,
          assignedAgent: task.assigned_agent,
          hasValidationWarnings: validationResult.flags.length > 0,
          validationFlagCount: validationResult.flags.length,
          modelUsed: (input.metadata as any)?.modelUsed || null
        }),
        created_at: now
      });
    }
  }

  // Return summary (first 300 chars of content)
  const summary = input.content.substring(0, 300) + (input.content.length > 300 ? '...' : '');
  const wordCount = input.content.split(/\s+/).filter(w => w.length > 0).length;

  const result: WorkProductStoreResult = {
    id,
    taskId: input.taskId,
    summary,
    wordCount,
    createdAt: now,
  };

  // Include validation info if there were warnings
  if (!validationResult.valid) {
    result.validation = {
      valid: validationResult.valid,
      flagCount: validationResult.flags.length,
      warnings: validationResult.flags.map(f => f.message),
      rejected: validationResult.rejected,
      feedback: validationResult.actionableFeedback,
    };
  }

  return result;
}

export function workProductGet(
  db: DatabaseClient,
  input: WorkProductGetInput
): {
  id: string;
  taskId: string;
  type: string;
  title: string;
  content: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  confidence: number | null;
} | null {
  const wp = db.getWorkProduct(input.id);
  if (!wp) return null;

  return {
    id: wp.id,
    taskId: wp.task_id,
    type: wp.type,
    title: wp.title,
    content: wp.content,
    metadata: JSON.parse(wp.metadata),
    createdAt: wp.created_at,
    confidence: wp.confidence
  };
}

export function workProductList(
  db: DatabaseClient,
  input: WorkProductListInput
): Array<{
  id: string;
  type: string;
  title: string;
  summary: string;
  wordCount: number;
  createdAt: string;
  confidence: number | null;
}> {
  const workProducts = db.listWorkProducts(input.taskId);

  return workProducts.map(wp => {
    const summary = wp.content.substring(0, 300) + (wp.content.length > 300 ? '...' : '');
    const wordCount = wp.content.split(/\s+/).filter(w => w.length > 0).length;

    return {
      id: wp.id,
      type: wp.type,
      title: wp.title,
      summary,
      wordCount,
      createdAt: wp.created_at,
      confidence: wp.confidence
    };
  });
}
