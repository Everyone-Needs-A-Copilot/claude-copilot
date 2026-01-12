/**
 * MCP Tools for Security Hook Management
 *
 * Provides tools to register, test, and manage PreToolUse security hooks.
 */

import type { DatabaseClient } from '../database.js';
import {
  SecurityRule,
  SecurityAction,
  evaluatePreToolUse,
  testSecurityRules,
  registerSecurityRule,
  unregisterSecurityRule,
  getSecurityRules,
  getSecurityRule,
  toggleSecurityRule
} from '../hooks/pre-tool-use.js';
import { initializeDefaultSecurityRules, getDefaultRuleIds } from '../hooks/security-rules.js';

// ============================================================================
// TOOL INPUT TYPES
// ============================================================================

export interface HookRegisterSecurityInput {
  rules?: Array<{
    id: string;
    name: string;
    description: string;
    enabled?: boolean;
    priority?: number;
    patterns?: string[]; // Regex patterns as strings
    severity?: 'low' | 'medium' | 'high' | 'critical';
    action?: 'allow' | 'warn' | 'block';
  }>;
  resetToDefaults?: boolean;
}

export interface HookListSecurityInput {
  includeDisabled?: boolean;
  ruleId?: string;
}

export interface HookTestSecurityInput {
  toolName: string;
  toolInput: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface HookToggleSecurityInput {
  ruleId: string;
  enabled: boolean;
}

// ============================================================================
// TOOL IMPLEMENTATIONS
// ============================================================================

/**
 * Register custom security rules or reset to defaults
 */
export function hookRegisterSecurity(
  _db: DatabaseClient,
  input: HookRegisterSecurityInput
): {
  success: boolean;
  registered: string[];
  message: string;
} {
  const registered: string[] = [];

  try {
    // Reset to defaults if requested
    if (input.resetToDefaults) {
      // Clear existing rules
      const existingRules = getSecurityRules();
      existingRules.forEach(rule => unregisterSecurityRule(rule.id));

      // Re-initialize defaults
      initializeDefaultSecurityRules();

      return {
        success: true,
        registered: getDefaultRuleIds(),
        message: 'Security rules reset to defaults'
      };
    }

    // Register custom rules
    if (input.rules && input.rules.length > 0) {
      for (const ruleInput of input.rules) {
        // Create SecurityRule from input
        const rule: SecurityRule = {
          id: ruleInput.id,
          name: ruleInput.name,
          description: ruleInput.description,
          enabled: ruleInput.enabled ?? true,
          priority: ruleInput.priority ?? 50,
          category: 'security',
          evaluate: (context) => {
            // Custom rule evaluation based on patterns
            if (!ruleInput.patterns || ruleInput.patterns.length === 0) {
              return null;
            }

            const contentStrings = Object.values(context.toolInput)
              .filter((v): v is string => typeof v === 'string');

            const allContent = contentStrings.join('\n');

            for (const patternStr of ruleInput.patterns) {
              try {
                const regex = new RegExp(patternStr, 'i');
                if (regex.test(allContent)) {
                  const actionMap: Record<string, SecurityAction> = {
                    allow: SecurityAction.ALLOW,
                    warn: SecurityAction.WARN,
                    block: SecurityAction.BLOCK
                  };

                  return {
                    action: actionMap[ruleInput.action || 'warn'],
                    ruleName: ruleInput.id,
                    reason: `Matched pattern: ${patternStr}`,
                    severity: ruleInput.severity || 'medium',
                    matchedPattern: patternStr,
                    recommendation: `Review ${context.toolName} call for security concerns`
                  };
                }
              } catch (error) {
                console.error(`Invalid pattern in rule ${ruleInput.id}:`, error);
              }
            }

            return null;
          }
        };

        registerSecurityRule(rule);
        registered.push(rule.id);
      }
    }

    return {
      success: true,
      registered,
      message: `Registered ${registered.length} custom security rule(s)`
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return {
      success: false,
      registered,
      message: `Failed to register rules: ${message}`
    };
  }
}

/**
 * List active security rules
 */
export function hookListSecurity(
  _db: DatabaseClient,
  input: HookListSecurityInput
): {
  rules: Array<{
    id: string;
    name: string;
    description: string;
    enabled: boolean;
    priority: number;
  }>;
  totalCount: number;
  enabledCount: number;
} {
  // Get specific rule
  if (input.ruleId) {
    const rule = getSecurityRule(input.ruleId);
    if (!rule) {
      return {
        rules: [],
        totalCount: 0,
        enabledCount: 0
      };
    }

    return {
      rules: [{
        id: rule.id,
        name: rule.name,
        description: rule.description,
        enabled: rule.enabled,
        priority: rule.priority
      }],
      totalCount: 1,
      enabledCount: rule.enabled ? 1 : 0
    };
  }

  // Get all rules
  const allRules = getSecurityRules();
  const rules = (input.includeDisabled ? allRules : allRules.filter(r => r.enabled))
    .map(rule => ({
      id: rule.id,
      name: rule.name,
      description: rule.description,
      enabled: rule.enabled,
      priority: rule.priority
    }));

  return {
    rules,
    totalCount: allRules.length,
    enabledCount: allRules.filter(r => r.enabled).length
  };
}

/**
 * Test security rules without executing tool
 */
export async function hookTestSecurity(
  _db: DatabaseClient,
  input: HookTestSecurityInput
): Promise<{
  toolName: string;
  allowed: boolean;
  action: 'allow' | 'warn' | 'block';
  violations: Array<{
    ruleName: string;
    reason: string;
    severity: string;
    recommendation?: string;
  }>;
  warnings: Array<{
    ruleName: string;
    reason: string;
    severity: string;
    recommendation?: string;
  }>;
  executionTime: number;
}> {
  const result = await testSecurityRules(input.toolName, input.toolInput);

  const actionMap: Record<number, 'allow' | 'warn' | 'block'> = {
    [SecurityAction.ALLOW]: 'allow',
    [SecurityAction.WARN]: 'warn',
    [SecurityAction.BLOCK]: 'block',
    [SecurityAction.TRANSFORM]: 'allow' // TRANSFORM is effectively allowed
  };

  return {
    toolName: input.toolName,
    allowed: result.allowed,
    action: actionMap[result.action] ?? 'allow',
    violations: result.violations.map(v => ({
      ruleName: v.ruleName,
      reason: v.reason,
      severity: v.severity,
      recommendation: v.recommendation
    })),
    warnings: result.warnings.map(w => ({
      ruleName: w.ruleName,
      reason: w.reason,
      severity: w.severity,
      recommendation: w.recommendation
    })),
    executionTime: result.executionTime
  };
}

/**
 * Enable or disable a security rule
 */
export function hookToggleSecurity(
  _db: DatabaseClient,
  input: HookToggleSecurityInput
): {
  success: boolean;
  ruleId: string;
  enabled: boolean;
  message: string;
} {
  const success = toggleSecurityRule(input.ruleId, input.enabled);

  if (!success) {
    return {
      success: false,
      ruleId: input.ruleId,
      enabled: false,
      message: `Rule '${input.ruleId}' not found`
    };
  }

  return {
    success: true,
    ruleId: input.ruleId,
    enabled: input.enabled,
    message: `Rule '${input.ruleId}' ${input.enabled ? 'enabled' : 'disabled'}`
  };
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize security hooks system with default rules
 */
export function initializeSecurityHooks(): void {
  initializeDefaultSecurityRules();
}
