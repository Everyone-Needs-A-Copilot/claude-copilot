/**
 * Validation module exports
 */

// Work Product Validation (existing)
export * from './types.js';
export * from './default-rules.js';
export * from './validator.js';

// Iteration Validation (Ralph Wiggum)
export * from './iteration-types.js';
export type { ValidationContext } from './iteration-hook-types.js';
export * from './iteration-engine.js';
export * from './iteration-default-config.js';
