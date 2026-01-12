/**
 * Default Security Rules for PreToolUse Hooks
 *
 * Provides out-of-the-box protection against common security issues:
 * - Secret detection (API keys, passwords, tokens)
 * - Destructive command detection (rm -rf, DROP TABLE, etc.)
 * - Sensitive file protection (.env, credentials, private keys)
 */

import {
  HookAction,
  type PreToolUseRule,
  type ToolCallContext,
  type HookRuleResult,
  extractStringContent,
  isFileWriteTool,
  isCommandExecutionTool,
  extractFilePaths,
  registerPreToolUseRule
} from './pre-tool-use.js';

// Backward compatibility aliases
const SecurityAction = HookAction;
type SecurityRule = PreToolUseRule;
type SecurityRuleResult = HookRuleResult;
const registerSecurityRule = registerPreToolUseRule;

// ============================================================================
// SECRET DETECTION PATTERNS
// ============================================================================

const SECRET_PATTERNS = [
  // API Keys
  {
    name: 'Generic API Key',
    pattern: /\b([A-Za-z0-9_-]{20,})\b/,
    keywords: ['api_key', 'apikey', 'api-key', 'key'],
    severity: 'high' as const
  },
  // AWS
  {
    name: 'AWS Access Key',
    pattern: /AKIA[0-9A-Z]{16}/,
    severity: 'critical' as const
  },
  {
    name: 'AWS Secret Key',
    pattern: /[A-Za-z0-9/+=]{40}/,
    keywords: ['aws_secret', 'secret_access_key'],
    severity: 'critical' as const
  },
  // Google Cloud
  {
    name: 'Google API Key',
    pattern: /AIza[0-9A-Za-z_-]{35}/,
    severity: 'critical' as const
  },
  // GitHub
  {
    name: 'GitHub Token',
    pattern: /gh[pousr]_[A-Za-z0-9_]{36,}/,
    severity: 'critical' as const
  },
  {
    name: 'GitHub Classic Token',
    pattern: /ghp_[A-Za-z0-9]{36}/,
    severity: 'critical' as const
  },
  // Stripe
  {
    name: 'Stripe API Key',
    pattern: /sk_live_[0-9a-zA-Z]{24,}/,
    severity: 'critical' as const
  },
  // Slack
  {
    name: 'Slack Token',
    pattern: /xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}/,
    severity: 'high' as const
  },
  // JWT
  {
    name: 'JWT Token',
    pattern: /eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*/,
    severity: 'medium' as const
  },
  // Generic Password
  {
    name: 'Password Assignment',
    pattern: /password\s*[=:]\s*["']([^"']{6,})["']/i,
    severity: 'high' as const
  },
  // Database Connection Strings
  {
    name: 'Database Connection String',
    pattern: /(postgres|mysql|mongodb):\/\/[^:]+:[^@]+@/i,
    severity: 'critical' as const
  },
  // Private Keys
  {
    name: 'Private Key',
    pattern: /-----BEGIN (RSA|DSA|EC|OPENSSH) PRIVATE KEY-----/,
    severity: 'critical' as const
  }
];

// ============================================================================
// DESTRUCTIVE COMMAND PATTERNS
// ============================================================================

const DESTRUCTIVE_COMMANDS = [
  // File system
  { pattern: /rm\s+-rf\s+\//, severity: 'critical' as const, description: 'Recursive force delete from root' },
  { pattern: /rm\s+-rf\s+~/, severity: 'critical' as const, description: 'Recursive force delete from home' },
  { pattern: /rm\s+-rf\s+\*/, severity: 'high' as const, description: 'Recursive force delete all files' },
  { pattern: /:\(\)\{\s*:\|:&\s*\};:/, severity: 'critical' as const, description: 'Fork bomb' },

  // Database
  { pattern: /DROP\s+(DATABASE|TABLE|SCHEMA)/i, severity: 'critical' as const, description: 'Database DROP operation' },
  { pattern: /TRUNCATE\s+TABLE/i, severity: 'high' as const, description: 'Table truncation' },
  { pattern: /DELETE\s+FROM\s+\w+\s*;/i, severity: 'high' as const, description: 'Unfiltered DELETE' },

  // System
  { pattern: /shutdown|reboot|halt/i, severity: 'critical' as const, description: 'System shutdown command' },
  { pattern: /mkfs|dd\s+if=/i, severity: 'critical' as const, description: 'Disk formatting command' },
  { pattern: /chmod\s+777/i, severity: 'medium' as const, description: 'Overly permissive file permissions' },

  // Package managers
  { pattern: /npm\s+publish\s+--force/, severity: 'high' as const, description: 'Force npm publish' },
  { pattern: /pip\s+install\s+--force-reinstall/, severity: 'medium' as const, description: 'Force pip reinstall' }
];

// ============================================================================
// SENSITIVE FILE PATTERNS
// ============================================================================

const SENSITIVE_FILES = [
  // Environment files
  { pattern: /\.env(\.local|\.production)?$/, severity: 'critical' as const },
  { pattern: /\.env\.[a-z]+$/, severity: 'critical' as const },

  // Credentials
  { pattern: /credentials?(\.json|\.yaml|\.yml)?$/i, severity: 'critical' as const },
  { pattern: /secrets?(\.json|\.yaml|\.yml)?$/i, severity: 'critical' as const },
  { pattern: /\.password$/i, severity: 'critical' as const },

  // SSH/SSL
  { pattern: /id_rsa|id_dsa|id_ed25519$/i, severity: 'critical' as const },
  { pattern: /\.pem$/, severity: 'high' as const },
  { pattern: /\.key$/, severity: 'high' as const },
  { pattern: /\.crt$/, severity: 'medium' as const },

  // Cloud provider configs
  { pattern: /\.aws\/credentials$/i, severity: 'critical' as const },
  { pattern: /\.kube\/config$/i, severity: 'critical' as const },
  { pattern: /gcloud\/credentials\.json$/i, severity: 'critical' as const },

  // Database
  { pattern: /\.sqlite3?$/i, severity: 'medium' as const },
  { pattern: /database\.yml$/i, severity: 'high' as const }
];

// ============================================================================
// RULE IMPLEMENTATIONS
// ============================================================================

/**
 * Rule: Detect secrets in file writes
 */
const secretDetectionRule: SecurityRule = {
  id: 'secret-detection',
  name: 'Secret Detection',
  description: 'Blocks writes containing API keys, passwords, tokens, or other secrets',
  enabled: true,
  priority: 90,
  category: 'security',
  evaluate(context: ToolCallContext): SecurityRuleResult | null {
    if (!isFileWriteTool(context.toolName)) {
      return null;
    }

    const content = extractStringContent(context.toolInput);
    const allText = content.join('\n');

    for (const secretPattern of SECRET_PATTERNS) {
      const match = allText.match(secretPattern.pattern);

      if (match) {
        // If pattern has keywords, check if they're present nearby
        if (secretPattern.keywords) {
          const hasKeyword = secretPattern.keywords.some(kw =>
            allText.toLowerCase().includes(kw.toLowerCase())
          );
          if (!hasKeyword) continue;
        }

        return {
          action: SecurityAction.BLOCK,
          ruleName: 'secret-detection',
          reason: `Detected potential ${secretPattern.name} in file write`,
          severity: secretPattern.severity,
          matchedPattern: match[0].substring(0, 20) + '...',
          recommendation: 'Use environment variables or secure secret management instead'
        };
      }
    }

    return null;
  }
};

/**
 * Rule: Detect destructive commands
 */
const destructiveCommandRule: SecurityRule = {
  id: 'destructive-command',
  name: 'Destructive Command Detection',
  description: 'Warns on destructive commands like rm -rf, DROP TABLE, etc.',
  enabled: true,
  priority: 85,
  category: 'security',
  evaluate(context: ToolCallContext): SecurityRuleResult | null {
    if (!isCommandExecutionTool(context.toolName)) {
      return null;
    }

    const content = extractStringContent(context.toolInput);
    const commandText = content.join(' ');

    for (const cmd of DESTRUCTIVE_COMMANDS) {
      if (cmd.pattern.test(commandText)) {
        const action = cmd.severity === 'critical'
          ? SecurityAction.BLOCK
          : SecurityAction.WARN;

        return {
          action,
          ruleName: 'destructive-command',
          reason: `Detected destructive command: ${cmd.description}`,
          severity: cmd.severity,
          matchedPattern: cmd.pattern.source,
          recommendation: action === SecurityAction.BLOCK
            ? 'This command is blocked for safety. Review and execute manually if needed.'
            : 'Review this command carefully before execution.'
        };
      }
    }

    return null;
  }
};

/**
 * Rule: Protect sensitive files
 */
const sensitiveFileRule: SecurityRule = {
  id: 'sensitive-file-protection',
  name: 'Sensitive File Protection',
  description: 'Blocks or warns when editing sensitive files like .env, credentials, private keys',
  enabled: true,
  priority: 80,
  category: 'security',
  evaluate(context: ToolCallContext): SecurityRuleResult | null {
    if (!isFileWriteTool(context.toolName)) {
      return null;
    }

    const filePaths = extractFilePaths(context.toolInput);

    for (const filePath of filePaths) {
      for (const sensitivePattern of SENSITIVE_FILES) {
        if (sensitivePattern.pattern.test(filePath)) {
          const action = sensitivePattern.severity === 'critical'
            ? SecurityAction.BLOCK
            : SecurityAction.WARN;

          return {
            action,
            ruleName: 'sensitive-file-protection',
            reason: `Attempting to modify sensitive file: ${filePath}`,
            severity: sensitivePattern.severity,
            matchedPattern: sensitivePattern.pattern.source,
            recommendation: action === SecurityAction.BLOCK
              ? 'Sensitive files should be edited manually with proper verification.'
              : 'Verify changes to sensitive files carefully.'
          };
        }
      }
    }

    return null;
  }
};

/**
 * Rule: Detect hardcoded URLs with credentials
 */
const credentialUrlRule: SecurityRule = {
  id: 'credential-url',
  name: 'Credential URL Detection',
  description: 'Blocks URLs containing embedded credentials',
  enabled: true,
  priority: 88,
  category: 'security',
  evaluate(context: ToolCallContext): SecurityRuleResult | null {
    if (!isFileWriteTool(context.toolName)) {
      return null;
    }

    const content = extractStringContent(context.toolInput);
    const allText = content.join('\n');

    // Pattern: protocol://user:pass@host
    const credUrlPattern = /https?:\/\/[^:]+:[^@]+@/i;

    if (credUrlPattern.test(allText)) {
      return {
        action: SecurityAction.BLOCK,
        ruleName: 'credential-url',
        reason: 'Detected URL with embedded credentials',
        severity: 'critical',
        matchedPattern: 'http(s)://user:password@host',
        recommendation: 'Use environment variables or authentication tokens instead'
      };
    }

    return null;
  }
};

/**
 * Rule: Prevent committing common secret files
 */
const gitSecretCommitRule: SecurityRule = {
  id: 'git-secret-commit',
  name: 'Git Secret Commit Prevention',
  description: 'Warns when attempting to commit commonly ignored secret files',
  enabled: true,
  priority: 75,
  category: 'security',
  evaluate(context: ToolCallContext): SecurityRuleResult | null {
    // This rule would integrate with git operations
    // For now, it's a placeholder for future git integration
    return null;
  }
};

// ============================================================================
// RULE REGISTRATION
// ============================================================================

/**
 * Initialize and register all default security rules
 */
export function initializeDefaultSecurityRules(): void {
  registerSecurityRule(secretDetectionRule);
  registerSecurityRule(destructiveCommandRule);
  registerSecurityRule(sensitiveFileRule);
  registerSecurityRule(credentialUrlRule);
  registerSecurityRule(gitSecretCommitRule);
}

/**
 * Get list of all default rule IDs
 */
export function getDefaultRuleIds(): string[] {
  return [
    'secret-detection',
    'destructive-command',
    'sensitive-file-protection',
    'credential-url',
    'git-secret-commit'
  ];
}
