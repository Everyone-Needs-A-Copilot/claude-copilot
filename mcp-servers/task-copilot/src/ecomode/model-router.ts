/**
 * Model Router for Ecomode
 *
 * Routes tasks to appropriate model (haiku/sonnet/opus) based on complexity score.
 * Determines effort level for Opus 4.6 adaptive thinking.
 * Supports modifier keywords for explicit model overrides.
 *
 * @see PRD-omc-learnings (OMC Learnings Integration)
 */

import { calculateComplexityScore, type ComplexityScoringInput } from './complexity-scorer.js';
import type { ComplexityScore, ModelRoute, ModifierKeyword, EffortLevel } from '../types/omc-features.js';

// ============================================================================
// ROUTING THRESHOLDS
// ============================================================================

/**
 * Default thresholds for model routing
 */
export const DEFAULT_THRESHOLDS = {
  /** Below this = haiku (low complexity) */
  low: 0.3,

  /** Below this = sonnet (medium complexity) */
  medium: 0.7,

  /** Above medium = opus (high complexity) */
} as const;

/**
 * Configurable thresholds
 */
export interface RoutingThresholds {
  /** Below this = haiku */
  low: number;

  /** Below this = sonnet */
  medium: number;
}

// ============================================================================
// MODIFIER KEYWORD DETECTION
// ============================================================================

/**
 * Detect modifier keywords in task text
 *
 * Supported keywords: eco:, fast:, max:, opus:, sonnet:, haiku:, auto:, ralph:
 */
export function detectModifierKeyword(text: string): ModifierKeyword | null {
  const patterns: Array<{
    regex: RegExp;
    keyword: ModifierKeyword['keyword'];
    targetModel: ModifierKeyword['targetModel'];
    effortLevel: ModifierKeyword['effortLevel'];
  }> = [
    { regex: /\beco:/i, keyword: 'eco', targetModel: null, effortLevel: 'low' },
    { regex: /\bfast:/i, keyword: 'fast', targetModel: null, effortLevel: 'medium' },
    { regex: /\bmax:/i, keyword: 'max', targetModel: null, effortLevel: 'max' },
    { regex: /\bopus:/i, keyword: 'opus', targetModel: 'opus', effortLevel: null },
    { regex: /\bsonnet:/i, keyword: 'sonnet', targetModel: 'sonnet', effortLevel: null },
    { regex: /\bhaiku:/i, keyword: 'haiku', targetModel: 'haiku', effortLevel: null },
    { regex: /\bauto:/i, keyword: 'auto', targetModel: null, effortLevel: null },
    { regex: /\bralph:/i, keyword: 'ralph', targetModel: null, effortLevel: null }, // ralph = auto-select
  ];

  for (const { regex, keyword, targetModel, effortLevel } of patterns) {
    const match = regex.exec(text);
    if (match) {
      return {
        keyword,
        position: match.index,
        raw: match[0],
        targetModel,
        effortLevel,
      };
    }
  }

  return null;
}

/**
 * Strip modifier keywords from text
 */
export function stripModifierKeywords(text: string): string {
  // Remove all known modifier keywords
  return text.replace(/\b(eco|fast|max|opus|sonnet|haiku|auto|ralph):/gi, '').trim();
}

// ============================================================================
// MODEL ROUTING LOGIC
// ============================================================================

/**
 * Determine cost tier based on model
 */
function getCostTier(model: ModelRoute['model']): ModelRoute['costTier'] {
  switch (model) {
    case 'haiku':
      return 'low';
    case 'sonnet':
      return 'medium';
    case 'opus':
      return 'high';
  }
}

/**
 * Determine effort level based on complexity score
 *
 * Effort mapping (aligned with Opus 4.6 adaptive thinking):
 * - score < 0.3: low (trivial tasks, quick responses)
 * - score 0.3-0.7: high (standard tasks, default reasoning depth)
 * - score > 0.7: max (complex architecture/design, deep reasoning)
 *
 * Note: 'medium' is reserved for future use or explicit overrides
 */
function getEffortLevel(score: ComplexityScore): EffortLevel {
  if (score.score < 0.3) {
    return 'low';
  } else if (score.score < 0.7) {
    return 'high'; // Default for most tasks
  } else {
    return 'max';
  }
}

/**
 * Route to model based on complexity score
 */
function routeByComplexity(score: ComplexityScore, thresholds: RoutingThresholds): ModelRoute {
  let model: ModelRoute['model'];
  let reason: string;

  if (score.score < thresholds.low) {
    model = 'haiku';
    reason = `Low complexity (${score.score.toFixed(2)}) → haiku. ${score.reasoning}`;
  } else if (score.score < thresholds.medium) {
    model = 'sonnet';
    reason = `Medium complexity (${score.score.toFixed(2)}) → sonnet. ${score.reasoning}`;
  } else {
    model = 'opus';
    reason = `High complexity (${score.score.toFixed(2)}) → opus. ${score.reasoning}`;
  }

  const effortLevel = getEffortLevel(score);

  return {
    model,
    confidence: 0.85, // High confidence in complexity-based routing
    reason,
    isOverride: false,
    costTier: getCostTier(model),
    effortLevel,
  };
}

/**
 * Route to model based on modifier keyword override
 *
 * Note: Effort-specific modifiers (eco:, fast:, max:) set effortLevel directly.
 * Model-specific modifiers (opus:, sonnet:, haiku:) use complexity-based effort.
 */
function routeByModifier(modifier: ModifierKeyword, complexityScore?: ComplexityScore): ModelRoute {
  if (modifier.targetModel) {
    // Explicit model override (opus:, sonnet:, haiku:)
    // Use complexity-based effort if available, otherwise default to 'high'
    const effortLevel = complexityScore ? getEffortLevel(complexityScore) : 'high';

    return {
      model: modifier.targetModel,
      confidence: 1.0, // Maximum confidence for explicit overrides
      reason: `User override: ${modifier.keyword}: → ${modifier.targetModel}`,
      isOverride: true,
      costTier: getCostTier(modifier.targetModel),
      effortLevel,
    };
  }

  // eco:, fast:, max:, auto:, ralph: means defer to complexity for model
  // But use modifier's effort level if specified (eco=low, fast=medium, max=max)
  // Return placeholder values - will be overridden by complexity routing
  return {
    model: 'haiku', // Will be overridden by complexity
    confidence: 0.0,
    reason: `Auto-routing enabled (${modifier.keyword}:)`,
    isOverride: false,
    costTier: 'low',
    effortLevel: modifier.effortLevel || 'high', // Use modifier effort if set, otherwise default
  };
}

// ============================================================================
// PUBLIC API
// ============================================================================

/**
 * Input for model routing
 */
export interface ModelRoutingInput extends ComplexityScoringInput {
  /** Optional routing thresholds (defaults to DEFAULT_THRESHOLDS) */
  thresholds?: RoutingThresholds;
}

/**
 * Result of model routing with complexity breakdown
 */
export interface ModelRoutingResult {
  /** Final routing decision */
  route: ModelRoute;

  /** Complexity score used for routing */
  complexityScore: ComplexityScore;

  /** Detected modifier keyword if any */
  modifier: ModifierKeyword | null;
}

/**
 * Route task to appropriate model based on complexity and modifiers
 *
 * @param input - Task information with optional thresholds
 * @returns ModelRoutingResult with route decision and complexity breakdown
 *
 * @example
 * ```typescript
 * const result = routeToModel({
 *   title: 'Fix login bug',
 *   fileCount: 1,
 *   agentId: 'qa'
 * });
 * // result.route.model = 'haiku'
 * // result.complexityScore.score = 0.23
 * ```
 *
 * @example
 * ```typescript
 * const result = routeToModel({
 *   title: 'opus: Design authentication architecture',
 *   fileCount: 10,
 *   agentId: 'ta'
 * });
 * // result.route.model = 'opus' (override)
 * // result.route.isOverride = true
 * ```
 */
export function routeToModel(input: ModelRoutingInput): ModelRoutingResult {
  const thresholds = input.thresholds ?? DEFAULT_THRESHOLDS;

  // Detect modifier keywords
  const combinedText = [input.title, input.description, input.context].filter(Boolean).join(' ');
  const modifier = detectModifierKeyword(combinedText);

  // Calculate complexity score (strip modifiers first for accurate scoring)
  const cleanTitle = modifier ? stripModifierKeywords(input.title) : input.title;
  const cleanDescription = modifier && input.description ? stripModifierKeywords(input.description) : input.description;

  const complexityScore = calculateComplexityScore({
    ...input,
    title: cleanTitle,
    description: cleanDescription,
  });

  // Route based on modifier or complexity
  let route: ModelRoute;

  if (modifier && modifier.targetModel) {
    // Explicit model override (opus:, sonnet:, haiku:) - pass complexity score for effort level
    route = routeByModifier(modifier, complexityScore);
  } else if (modifier && !modifier.targetModel) {
    // Effort-level modifiers (eco:, fast:, max:) or auto-routing (auto:, ralph:)
    // Use complexity-based routing for model selection
    route = routeByComplexity(complexityScore, thresholds);
    route.reason = `Auto-routing (${modifier.keyword}:): ${route.reason}`;

    // Override effort level if modifier specifies one
    if (modifier.effortLevel) {
      route.effortLevel = modifier.effortLevel;
      route.reason += ` [effort: ${modifier.effortLevel}]`;
    }
  } else {
    // No modifier, use complexity
    route = routeByComplexity(complexityScore, thresholds);
  }

  return {
    route,
    complexityScore,
    modifier,
  };
}

/**
 * Batch route multiple tasks
 *
 * More efficient than calling routeToModel multiple times.
 */
export function routeToModelBatch(inputs: ModelRoutingInput[]): ModelRoutingResult[] {
  return inputs.map((input) => routeToModel(input));
}

/**
 * Get recommended model for a task (simple API without full routing result)
 */
export function getRecommendedModel(
  title: string,
  options?: {
    description?: string;
    fileCount?: number;
    agentId?: string;
    thresholds?: RoutingThresholds;
  }
): ModelRoute['model'] {
  const result = routeToModel({
    title,
    description: options?.description,
    fileCount: options?.fileCount,
    agentId: options?.agentId,
    thresholds: options?.thresholds,
  });

  return result.route.model;
}

/**
 * Recommend model for a task with agent and task metadata
 *
 * Resolution order:
 * 1. task.metadata.modelOverride (highest priority)
 * 2. agent.model (from agent frontmatter)
 * 3. Complexity-based routing (fallback)
 * 4. 'sonnet' (system default)
 *
 * Fallback heuristics (only when no explicit model configured):
 * - Orchestration keywords (ultrawork, orchestrate, parallel) → opus
 * - Simple/quick keywords (typo, simple, quick) → haiku
 * - Default → sonnet
 *
 * Note: This is a simplified API that only returns the model.
 * For full routing with effort level, use routeToModel() instead.
 *
 * @param task - Task metadata with title, description, metadata
 * @param agent - Agent configuration with default model
 * @returns Recommended model ('opus' | 'sonnet' | 'haiku')
 *
 * @example
 * ```typescript
 * const model = recommendModel(
 *   { title: 'Fix login bug', metadata: {} },
 *   { id: 'me', model: 'sonnet' }
 * );
 * // Returns: 'sonnet' (from agent default)
 *
 * const model = recommendModel(
 *   { title: 'orchestrate: parallel build', metadata: {} },
 *   { id: 'ta', model: 'opus' }
 * );
 * // Returns: 'opus' (orchestration keyword)
 *
 * const model = recommendModel(
 *   { title: 'Quick fix', metadata: { modelOverride: 'haiku' } },
 *   { id: 'me', model: 'sonnet' }
 * );
 * // Returns: 'haiku' (override takes precedence)
 * ```
 */
export function recommendModel(
  task: {
    title: string;
    description?: string;
    metadata?: {
      modelOverride?: 'opus' | 'sonnet' | 'haiku';
      complexity?: string;
      fileCount?: number;
    };
  },
  agent: {
    id: string;
    model?: 'opus' | 'sonnet' | 'haiku';
  }
): 'opus' | 'sonnet' | 'haiku' {
  // Priority 1: Task metadata override (highest)
  if (task.metadata?.modelOverride) {
    return task.metadata.modelOverride;
  }

  // Priority 2: Agent default model (from frontmatter)
  if (agent.model) {
    return agent.model;
  }

  // Priority 3: Keyword heuristics (fallback when no explicit model configured)
  const combinedText = [task.title, task.description].filter(Boolean).join(' ').toLowerCase();

  // Check for orchestration keywords → opus
  const orchestrationKeywords = [
    'ultrawork',
    'orchestrate',
    'parallel',
    'coordinate',
    'multi-stream',
    'concurrent'
  ];

  const hasOrchestrationKeyword = orchestrationKeywords.some(keyword =>
    combinedText.includes(keyword)
  );

  if (hasOrchestrationKeyword) {
    return 'opus';
  }

  // Check for simple/quick keywords → haiku
  const simpleKeywords = [
    'quick',
    'simple',
    'typo',
    'fix typo',
    'update text',
    'change wording'
  ];

  const hasSimpleKeyword = simpleKeywords.some(keyword =>
    combinedText.includes(keyword)
  );

  if (hasSimpleKeyword) {
    return 'haiku';
  }

  // Priority 4: Fallback to sonnet (system default)
  return 'sonnet';
}
