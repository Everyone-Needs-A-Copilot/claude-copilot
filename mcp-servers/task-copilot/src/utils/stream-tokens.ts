/**
 * Stream token utilities
 *
 * Provides lightweight estimates for per-stream token usage and budget checks.
 */

import type { DatabaseClient } from '../database.js';
import type { TaskMetadata } from '../types.js';

export function estimateTokensFromChars(chars: number): number {
  if (!Number.isFinite(chars) || chars <= 0) {
    return 0;
  }
  // M-1: Integer overflow protection
  const MAX_CHARS = 100_000_000; // 100M chars
  if (chars > MAX_CHARS) {
    throw new Error(`Content too large: ${chars} chars exceeds maximum ${MAX_CHARS}`);
  }
  return Math.ceil(chars / 4);
}

export function estimateTokensFromText(text: string): number {
  if (!text || text.trim().length === 0) {
    return 0;
  }
  return estimateTokensFromChars(text.length);
}

export function getStreamTokenBudgetFromMetadata(metadataList: TaskMetadata[]): number | null {
  let budget: number | null = null;

  for (const metadata of metadataList) {
    const value = metadata.streamTokenBudget;
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
      budget = budget === null ? value : Math.max(budget, value);
    }
  }

  return budget;
}

export function getStreamTokenBudget(
  db: DatabaseClient,
  streamId: string,
  initiativeId?: string
): number | null {
  let sql = `
    SELECT t.metadata
    FROM tasks t
  `;
  const params: unknown[] = [];

  if (initiativeId) {
    sql += `
      JOIN prds p ON t.prd_id = p.id
      WHERE p.initiative_id = ?
        AND json_extract(t.metadata, '$.streamId') = ?
    `;
    params.push(initiativeId, streamId);
  } else {
    sql += `
      WHERE json_extract(t.metadata, '$.streamId') = ?
    `;
    params.push(streamId);
  }

  const rows = db.getDb().prepare(sql).all(...params) as Array<{ metadata: string }>;
  if (rows.length === 0) return null;

  const metadataList = rows.map(row => JSON.parse(row.metadata) as TaskMetadata);
  return getStreamTokenBudgetFromMetadata(metadataList);
}

export function getStreamTokenUsage(
  db: DatabaseClient,
  streamId: string,
  initiativeId?: string,
  includeArchived: boolean = false
): number {
  let sql = `
    SELECT SUM(LENGTH(wp.content)) as total_chars
    FROM work_products wp
    JOIN tasks t ON wp.task_id = t.id
  `;
  const params: unknown[] = [];

  if (initiativeId) {
    sql += `
      JOIN prds p ON t.prd_id = p.id
      WHERE p.initiative_id = ?
        AND json_extract(t.metadata, '$.streamId') = ?
    `;
    params.push(initiativeId, streamId);
  } else {
    sql += `
      WHERE json_extract(t.metadata, '$.streamId') = ?
    `;
    params.push(streamId);
  }

  if (!includeArchived) {
    sql += ' AND (t.archived IS NULL OR t.archived = 0)';
  }

  const row = db.getDb().prepare(sql).get(...params) as { total_chars: number | null } | undefined;
  const totalChars = row?.total_chars ?? 0;
  return estimateTokensFromChars(totalChars);
}
