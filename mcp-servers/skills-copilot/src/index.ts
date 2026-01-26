#!/usr/bin/env node
/**
 * Skills Hub MCP Server
 *
 * On-demand skill loading from multiple sources:
 * - Private database (Postgres) for proprietary skills
 * - SkillsMP API for 25,000+ public skills
 * - Local files for git-synced skills
 * - SQLite cache for fast repeated access
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

import { SkillsMPProvider, PostgresProvider, CacheProvider, LocalProvider, KnowledgeRepoProvider } from './providers/index.js';
import type { SkillsHubConfig, Skill, SkillMeta, SkillMatch, SkillSource, SkillSaveParams, ResolvedExtension, ExtensionListItemWithSource, KnowledgeRepoStatus, KnowledgeRepoConfig, KnowledgeSearchResult, KnowledgeSearchOptions } from './types.js';
import { detectTriggeredSkills, formatTriggerMatches } from './triggers.js';
import { ConfidenceScorer, formatEvaluationResults, type EvaluationContext } from './evaluation/index.js';

// Configuration from environment
const config: SkillsHubConfig = {
  skillsmpApiKey: process.env.SKILLSMP_API_KEY,
  postgresUrl: process.env.POSTGRES_URL,
  cachePath: process.env.CACHE_PATH || '~/.claude/skills-cache',
  cacheTtlDays: parseInt(process.env.CACHE_TTL_DAYS || '7', 10),
  localSkillsPath: process.env.LOCAL_SKILLS_PATH || './.claude/skills',
  logLevel: (process.env.LOG_LEVEL || 'info') as SkillsHubConfig['logLevel']
};

// Knowledge repository configuration (two-tier: project + global)
// Project-specific path takes precedence over global ~/.claude/knowledge
const knowledgeRepoConfig: KnowledgeRepoConfig = {
  projectPath: process.env.KNOWLEDGE_REPO_PATH,  // Optional: project-specific override
  globalPath: process.env.GLOBAL_KNOWLEDGE_PATH  // Optional: defaults to ~/.claude/knowledge
};

// Initialize providers
const cache = new CacheProvider(config.cachePath, config.cacheTtlDays);
const local = new LocalProvider(config.localSkillsPath || '');
const skillsmp = config.skillsmpApiKey ? new SkillsMPProvider(config.skillsmpApiKey) : null;
const postgres = config.postgresUrl ? new PostgresProvider(config.postgresUrl) : null;
const knowledgeRepo = new KnowledgeRepoProvider(knowledgeRepoConfig);
const skillEvaluator = new ConfidenceScorer();

// Create MCP server
const server = new Server(
  {
    name: 'skills-hub',
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
    name: 'skill_get',
    description: 'Fetch a skill by name. Checks cache, then private DB, then SkillsMP, then local files.',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Skill name to fetch' },
        forceRefresh: { type: 'boolean', description: 'Skip cache and fetch fresh' }
      },
      required: ['name']
    }
  },
  {
    name: 'skill_search',
    description: 'Search for skills across all sources by query',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Search query' },
        source: {
          type: 'string',
          enum: ['private', 'skillsmp', 'local', 'all'],
          description: 'Limit search to specific source'
        },
        limit: { type: 'number', description: 'Max results (default 10)' }
      },
      required: ['query']
    }
  },
  {
    name: 'skill_list',
    description: 'List available skills from specified source',
    inputSchema: {
      type: 'object',
      properties: {
        source: {
          type: 'string',
          enum: ['private', 'local', 'cache', 'all'],
          description: 'Source to list from (default: all)'
        }
      }
    }
  },
  {
    name: 'skill_save',
    description: 'Save a skill to the private database',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Skill name' },
        description: { type: 'string', description: 'Brief description' },
        content: { type: 'string', description: 'Full SKILL.md content' },
        category: { type: 'string', description: 'Category (e.g., analysis, engineering)' },
        keywords: {
          type: 'array',
          items: { type: 'string' },
          description: 'Keywords for matching'
        },
        tags: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional tags'
        },
        isProprietary: { type: 'boolean', description: 'Mark as proprietary (default: true)' }
      },
      required: ['name', 'description', 'content', 'keywords']
    }
  },
  {
    name: 'skill_cache_clear',
    description: 'Clear the skill cache',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Specific skill to clear (omit for all)' }
      }
    }
  },
  {
    name: 'skills_hub_status',
    description: 'Get status of all providers',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'skill_discover',
    description: 'Force re-scan of local skill directories (.claude/skills and ~/.claude/skills). Use when skills are added/modified outside the session.',
    inputSchema: {
      type: 'object',
      properties: {
        clearCache: {
          type: 'boolean',
          description: 'Clear cache before re-scanning (default: false)'
        }
      }
    }
  },
  {
    name: 'skill_auto_detect',
    description: 'Auto-detect skills based on file patterns and keywords in context. Returns skills whose triggers match the provided context.',
    inputSchema: {
      type: 'object',
      properties: {
        files: {
          type: 'array',
          items: { type: 'string' },
          description: 'File paths to analyze for trigger patterns (e.g., ["src/test.spec.ts", "README.md"])'
        },
        text: {
          type: 'string',
          description: 'Text content to analyze for trigger keywords (e.g., conversation or file content)'
        },
        limit: {
          type: 'number',
          description: 'Maximum number of skills to return (default: 5)'
        }
      }
    }
  },
  // Extension tools for knowledge repository integration
  {
    name: 'extension_get',
    description: 'Get extension for a specific agent from the knowledge repository. Returns the extension content, type, and required skills.',
    inputSchema: {
      type: 'object',
      properties: {
        agent: {
          type: 'string',
          description: 'Agent ID to get extension for (e.g., "sd", "uxd", "cw")',
          enum: ['me', 'ta', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw']
        }
      },
      required: ['agent']
    }
  },
  {
    name: 'extension_list',
    description: 'List all available extensions from the knowledge repository manifest',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  {
    name: 'manifest_status',
    description: 'Get status of the knowledge repository configuration and manifest',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  },
  // Knowledge search tools
  {
    name: 'knowledge_search',
    description: 'Search knowledge files across project and machine-level knowledge repositories. Searches file names, paths, and content. Use this to find information about company, products, brand, operations, etc.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search query (e.g., "company", "brand voice", "products")'
        },
        limit: {
          type: 'number',
          description: 'Maximum results to return (default: 5)'
        },
        directory: {
          type: 'string',
          description: 'Limit search to specific directory (e.g., "01-company", "02-products")'
        },
        includeContent: {
          type: 'boolean',
          description: 'Include full file content in results (default: false, returns snippets)'
        }
      },
      required: ['query']
    }
  },
  {
    name: 'knowledge_get',
    description: 'Get a specific knowledge file by path. Checks project-level first, then machine-level.',
    inputSchema: {
      type: 'object',
      properties: {
        path: {
          type: 'string',
          description: 'Relative path to the file (e.g., "01-company/00-overview.md")'
        }
      },
      required: ['path']
    }
  },
  // Skill evaluation tool
  {
    name: 'skill_evaluate',
    description: 'Evaluate context to find relevant skills with confidence scores. Combines file pattern matching and keyword detection. Returns ranked skills above threshold.',
    inputSchema: {
      type: 'object',
      properties: {
        files: {
          type: 'array',
          items: { type: 'string' },
          description: 'File paths to analyze for pattern matching (e.g., ["src/test.spec.ts", "config.json"])'
        },
        text: {
          type: 'string',
          description: 'Text content to analyze for keyword matching (e.g., prompt, conversation, file content)'
        },
        recentActivity: {
          type: 'array',
          items: { type: 'string' },
          description: 'Recent activity keywords for boosting (e.g., ["testing", "deployment"])'
        },
        threshold: {
          type: 'number',
          description: 'Minimum confidence score 0-1 (default: 0.3)'
        },
        limit: {
          type: 'number',
          description: 'Maximum results to return (default: 10)'
        },
        showDetails: {
          type: 'boolean',
          description: 'Include detailed match information (default: false)'
        }
      }
    }
  }
];

/**
 * Get skill from best available source
 */
async function getSkill(name: string, forceRefresh = false): Promise<{ skill: Skill | null; source: SkillSource }> {
  // 1. Check cache (unless forcing refresh)
  if (!forceRefresh) {
    const cached = cache.get(name);
    if (cached) {
      return {
        skill: {
          id: `cache-${name}`,
          name,
          description: '',
          content: cached.content,
          keywords: [],
          source: 'cache',
          version: '1.0.0',
          isProprietary: false
        },
        source: 'cache'
      };
    }
  }

  // 2. Check private database
  if (postgres?.isConnected()) {
    const result = await postgres.getSkill(name);
    if (result.success && result.data) {
      cache.set(name, result.data.content, 'private');
      return { skill: result.data, source: 'private' };
    }
  }

  // 3. Check SkillsMP
  if (skillsmp) {
    const result = await skillsmp.getSkillByName(name);
    if (result.success && result.data) {
      cache.set(name, result.data.content, 'skillsmp');
      return {
        skill: {
          id: result.data.meta.id,
          name: result.data.meta.name,
          description: result.data.meta.description,
          content: result.data.content,
          keywords: result.data.meta.keywords,
          author: result.data.meta.author,
          source: 'skillsmp',
          version: '1.0.0',
          isProprietary: false
        },
        source: 'skillsmp'
      };
    }
  }

  // 4. Check local files
  const localResult = local.getSkill(name);
  if (localResult.success && localResult.data) {
    cache.set(name, localResult.data.content, 'local');
    return { skill: localResult.data, source: 'local' };
  }

  return { skill: null, source: 'cache' };
}

/**
 * Search skills across sources
 */
async function searchSkills(
  query: string,
  source: 'private' | 'skillsmp' | 'local' | 'all' = 'all',
  limit = 10
): Promise<SkillMatch[]> {
  const results: SkillMatch[] = [];

  // Search private DB
  if ((source === 'all' || source === 'private') && postgres?.isConnected()) {
    const privateResults = await postgres.searchSkills(query, limit);
    if (privateResults.success && privateResults.data) {
      results.push(...privateResults.data);
    }
  }

  // Search SkillsMP
  if ((source === 'all' || source === 'skillsmp') && skillsmp) {
    const publicResults = await skillsmp.searchSkills(query, limit);
    if (publicResults.success && publicResults.data) {
      results.push(...publicResults.data);
    }
  }

  // Search local
  if (source === 'all' || source === 'local') {
    const localResults = local.searchSkills(query);
    if (localResults.success && localResults.data) {
      results.push(...localResults.data.map(m => ({ ...m, relevance: 0.5 })));
    }
  }

  // Sort by relevance and dedupe
  const seen = new Set<string>();
  return results
    .sort((a, b) => (b.relevance || 0) - (a.relevance || 0))
    .filter(skill => {
      if (seen.has(skill.name)) return false;
      seen.add(skill.name);
      return true;
    })
    .slice(0, limit);
}

/**
 * List skills from source
 */
async function listSkills(source: 'private' | 'local' | 'cache' | 'all' = 'all'): Promise<SkillMeta[]> {
  const results: SkillMeta[] = [];

  if ((source === 'all' || source === 'private') && postgres?.isConnected()) {
    const privateResults = await postgres.listSkills();
    if (privateResults.success && privateResults.data) {
      results.push(...privateResults.data);
    }
  }

  if (source === 'all' || source === 'local') {
    const localResults = local.listSkills();
    if (localResults.success && localResults.data) {
      results.push(...localResults.data);
    }
  }

  if (source === 'all' || source === 'cache') {
    const cachedSkills = cache.list();
    results.push(...cachedSkills.map(c => ({
      id: `cache-${c.name}`,
      name: c.name,
      description: `Cached from ${c.source}`,
      keywords: [],
      source: 'cache' as const
    })));
  }

  // Dedupe by name
  const seen = new Set<string>();
  return results.filter(skill => {
    if (seen.has(skill.name)) return false;
    seen.add(skill.name);
    return true;
  });
}

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
      case 'skill_get': {
        const result = await getSkill(
          a.name as string,
          a.forceRefresh as boolean | undefined
        );

        if (!result.skill) {
          return {
            content: [{
              type: 'text',
              text: `Skill not found: ${a.name}\n\nTry searching with skill_search to find available skills.`
            }]
          };
        }

        // Return the full skill content
        return {
          content: [{
            type: 'text',
            text: `# Skill: ${result.skill.name}\n\n**Source:** ${result.source}\n**Author:** ${result.skill.author || 'Unknown'}\n\n---\n\n${result.skill.content}`
          }]
        };
      }

      case 'skill_search': {
        const results = await searchSkills(
          a.query as string,
          a.source as 'private' | 'skillsmp' | 'local' | 'all' | undefined,
          a.limit as number | undefined
        );

        if (results.length === 0) {
          return {
            content: [{
              type: 'text',
              text: `No skills found for query: "${a.query}"`
            }]
          };
        }

        const table = results.map(s =>
          `| ${s.name} | ${s.source} | ${s.author || '-'} | ${s.description.slice(0, 60)}... |`
        ).join('\n');

        return {
          content: [{
            type: 'text',
            text: `## Search Results for "${a.query}"\n\n| Skill | Source | Author | Description |\n|-------|--------|--------|-------------|\n${table}\n\nUse \`skill_get(name)\` to load full content.`
          }]
        };
      }

      case 'skill_list': {
        const results = await listSkills(
          a.source as 'private' | 'local' | 'cache' | 'all' | undefined
        );

        // Get discovered skills for annotation
        const discoveredSkills = new Set(
          local.getDiscoveredSkills().map(s => s.skill.name)
        );

        const grouped: Record<string, SkillMeta[]> = {};
        for (const skill of results) {
          const src = skill.source;
          if (!grouped[src]) grouped[src] = [];
          grouped[src].push(skill);
        }

        let output = '## Available Skills\n\n';
        for (const [source, skills] of Object.entries(grouped)) {
          output += `### ${source.charAt(0).toUpperCase() + source.slice(1)} (${skills.length})\n\n`;
          output += '| Name | Category | Keywords | Discovery |\n|------|----------|----------|----------|\n';
          for (const skill of skills) {
            const discoveryStatus = discoveredSkills.has(skill.name) ? 'auto' : 'manifest';
            output += `| ${skill.name} | ${skill.category || '-'} | ${skill.keywords.slice(0, 3).join(', ')} | ${discoveryStatus} |\n`;
          }
          output += '\n';
        }

        output += '\n**Discovery methods:**\n';
        output += '- `auto`: Auto-discovered from .claude/skills directories\n';
        output += '- `manifest`: Loaded from configured skills path or knowledge manifest\n';

        return { content: [{ type: 'text', text: output }] };
      }

      case 'skill_save': {
        if (!postgres?.isConnected()) {
          return {
            content: [{ type: 'text', text: 'Error: PostgreSQL not connected. Cannot save skills.' }],
            isError: true
          };
        }

        const params: SkillSaveParams = {
          name: a.name as string,
          description: a.description as string,
          content: a.content as string,
          category: a.category as string | undefined,
          keywords: a.keywords as string[],
          tags: a.tags as string[] | undefined,
          isProprietary: a.isProprietary as boolean | undefined
        };

        // Validate skill size (500-line maximum)
        const lineCount = params.content.split('\n').length;
        const MAX_LINES = 500;
        const WARNING_THRESHOLD = 400;

        if (lineCount > MAX_LINES) {
          return {
            content: [{
              type: 'text',
              text: `Skill too large: ${lineCount} lines (max: ${MAX_LINES})

To reduce skill size:
- Split into multiple focused skills
- Move examples to separate files
- Remove verbose explanations
- Use concise syntax

Consider: Main skill + helper skills pattern`
            }],
            isError: true
          };
        }

        const result = await postgres.saveSkill(params);

        if (!result.success) {
          return {
            content: [{ type: 'text', text: `Error saving skill: ${result.error}` }],
            isError: true
          };
        }

        // Invalidate cache
        cache.invalidate(params.name);

        // Build response with line count and optional warning
        let responseText = `Skill saved successfully: ${params.name}\n\nID: ${result.data?.id}\nLine count: ${lineCount}`;

        if (lineCount >= WARNING_THRESHOLD && lineCount <= MAX_LINES) {
          responseText += `\n\n⚠️  Warning: Skill is ${lineCount} lines (approaching ${MAX_LINES} line limit).\nConsider splitting into multiple focused skills if it grows further.`;
        }

        return {
          content: [{
            type: 'text',
            text: responseText
          }]
        };
      }

      case 'skill_cache_clear': {
        if (a.name) {
          const cleared = cache.invalidate(a.name as string);
          return {
            content: [{
              type: 'text',
              text: cleared
                ? `Cache cleared for: ${a.name}`
                : `Skill not in cache: ${a.name}`
            }]
          };
        }

        cache.clear();
        return {
          content: [{ type: 'text', text: 'All cache cleared' }]
        };
      }

      case 'skill_discover': {
        const clearCache = a.clearCache as boolean | undefined;

        if (clearCache) {
          local.refresh();
        } else {
          local.rediscover();
        }

        const discovered = local.getDiscoveredSkills();
        const totalCount = local.getCount();

        let output = `## Skills Discovery ${clearCache ? '(with cache clear)' : '(re-scan)'}\n\n`;
        output += `**Total skills:** ${totalCount}\n`;
        output += `**Auto-discovered:** ${discovered.length}\n\n`;

        if (discovered.length > 0) {
          output += '### Discovered Skills\n\n';
          output += '| Name | Category | Path |\n';
          output += '|------|----------|------|\n';

          for (const { skill, path } of discovered) {
            const category = skill.category || '-';
            const shortPath = path.replace(process.env.HOME || '', '~');
            output += `| ${skill.name} | ${category} | ${shortPath} |\n`;
          }
        } else {
          output += 'No skills discovered in:\n';
          output += '- .claude/skills\n';
          output += '- ~/.claude/skills\n\n';
          output += 'Add SKILL.md files to these directories for auto-discovery.';
        }

        return {
          content: [{ type: 'text', text: output }]
        };
      }

      case 'skill_auto_detect': {
        const files = a.files as string[] | undefined;
        const text = a.text as string | undefined;
        const limit = a.limit as number | undefined || 5;

        if (!files && !text) {
          return {
            content: [{
              type: 'text',
              text: 'Error: Must provide either "files" or "text" parameter for trigger detection.'
            }],
            isError: true
          };
        }

        // Get all skill triggers
        const triggers = local.getAllTriggers();

        if (triggers.size === 0) {
          return {
            content: [{
              type: 'text',
              text: 'No skills have trigger definitions. Add trigger_files or trigger_keywords to SKILL.md frontmatter.'
            }]
          };
        }

        // Detect triggered skills
        const matches = detectTriggeredSkills(
          { files, text },
          triggers
        );

        // Format and return results
        const output = formatTriggerMatches(matches, limit);

        return {
          content: [{ type: 'text', text: output }]
        };
      }

      case 'skills_hub_status': {
        const cacheStats = cache.getStats();
        const localCount = local.getCount();
        const discoveredCount = local.getDiscoveredCount();
        const repoStatus = knowledgeRepo.getStatus();

        // Format knowledge repo status for display
        let knowledgeRepoDisplay = 'not configured';
        if (repoStatus.configured) {
          const parts: string[] = [];
          if (repoStatus.global?.loaded && repoStatus.global.manifest) {
            parts.push(`global: ${repoStatus.global.manifest.name} (${repoStatus.global.manifest.extensions} ext)`);
          } else if (repoStatus.global) {
            parts.push(`global: not loaded`);
          }
          if (repoStatus.project?.loaded && repoStatus.project.manifest) {
            parts.push(`project: ${repoStatus.project.manifest.name} (${repoStatus.project.manifest.extensions} ext)`);
          } else if (repoStatus.project) {
            parts.push(`project: not loaded`);
          }
          knowledgeRepoDisplay = parts.length > 0 ? parts.join(', ') : 'configured but not loaded';
        }

        const status = {
          providers: {
            postgres: postgres?.isConnected() ? 'connected' : 'not configured',
            skillsmp: skillsmp ? 'configured' : 'not configured',
            local: `${localCount} skills found (${discoveredCount} auto-discovered)`,
            cache: `${cacheStats.total} cached (${Math.round(cacheStats.size / 1024)}KB)`,
            knowledgeRepo: knowledgeRepoDisplay
          },
          config: {
            cachePath: config.cachePath,
            cacheTtlDays: config.cacheTtlDays,
            localSkillsPath: config.localSkillsPath,
            discoveryPaths: ['.claude/skills', '~/.claude/skills'],
            knowledgeRepo: {
              projectPath: knowledgeRepoConfig.projectPath || 'not set',
              globalPath: knowledgeRepoConfig.globalPath || '~/.claude/knowledge (default)'
            }
          }
        };

        return {
          content: [{ type: 'text', text: JSON.stringify(status, null, 2) }]
        };
      }

      // Extension tools for knowledge repository
      case 'extension_get': {
        const agentId = a.agent as string;

        if (!knowledgeRepo.isLoaded()) {
          const status = knowledgeRepo.getStatus();
          const globalPath = status.global?.path || '~/.claude/knowledge';
          return {
            content: [{
              type: 'text',
              text: `No knowledge repository loaded.\n\n**To enable extensions:**\n1. Create a global knowledge repo at \`${globalPath}\`\n2. Or set \`KNOWLEDGE_REPO_PATH\` for project-specific extensions\n\nSee EXTENSION-SPEC.md for details.`
            }]
          };
        }

        const extension = knowledgeRepo.getExtension(agentId);

        if (!extension) {
          return {
            content: [{
              type: 'text',
              text: `No extension found for agent: ${agentId}\n\nUse extension_list to see available extensions.`
            }]
          };
        }

        // Format the response
        const requiredSkillsNote = extension.requiredSkills.length > 0
          ? `\n\n**Required Skills:** ${extension.requiredSkills.join(', ')}`
          : '';

        return {
          content: [{
            type: 'text',
            text: `# Extension: @agent-${extension.agent}\n\n**Type:** ${extension.type}\n**Fallback:** ${extension.fallbackBehavior}${requiredSkillsNote}\n${extension.description ? `\n**Description:** ${extension.description}\n` : ''}\n---\n\n${extension.content}`
          }]
        };
      }

      case 'extension_list': {
        if (!knowledgeRepo.isLoaded()) {
          const status = knowledgeRepo.getStatus();
          const globalPath = status.global?.path || '~/.claude/knowledge';
          return {
            content: [{
              type: 'text',
              text: `No knowledge repository loaded.\n\n**To enable extensions:**\n1. Create a global knowledge repo at \`${globalPath}\`\n2. Or set \`KNOWLEDGE_REPO_PATH\` for project-specific extensions\n\nSee EXTENSION-SPEC.md for details.`
            }]
          };
        }

        const extensions = knowledgeRepo.listExtensions();

        if (extensions.length === 0) {
          return {
            content: [{
              type: 'text',
              text: `No extensions defined in the knowledge repository manifest.`
            }]
          };
        }

        let output = '## Available Extensions\n\n';
        output += '| Agent | Type | Source | Description | Required Skills |\n';
        output += '|-------|------|--------|-------------|------------------|\n';

        for (const ext of extensions) {
          const skills = ext.requiredSkills?.join(', ') || '-';
          const sourceLabel = ext.overridesGlobal ? `${ext.source} (overrides global)` : ext.source;
          output += `| @agent-${ext.agent} | ${ext.type} | ${sourceLabel} | ${ext.description || '-'} | ${skills} |\n`;
        }

        output += '\n\nUse `extension_get(agent)` to load the full extension content.';

        return { content: [{ type: 'text', text: output }] };
      }

      case 'manifest_status': {
        const status = knowledgeRepo.getStatus();

        // Add helpful information about the two-tier system
        const enrichedStatus = {
          ...status,
          resolution: 'project → global → base agents',
          howToEnable: {
            global: 'Create ~/.claude/knowledge/knowledge-manifest.json (auto-detected)',
            project: 'Set KNOWLEDGE_REPO_PATH in .mcp.json for project-specific overrides'
          }
        };

        return {
          content: [{
            type: 'text',
            text: JSON.stringify(enrichedStatus, null, 2)
          }]
        };
      }

      // Knowledge search tools
      case 'knowledge_search': {
        const query = a.query as string;

        // Check if knowledge repository is loaded
        if (!knowledgeRepo.isLoaded()) {
          const status = knowledgeRepo.getStatus();
          const globalPath = status.global?.path || '~/.claude/knowledge';

          // Detect if project expects knowledge (contextual prompt)
          const cwd = process.cwd();
          const expectation = knowledgeRepo.detectKnowledgeExpectation(cwd);
          const teamDetection = knowledgeRepo.detectTeamMemberStatus(cwd);

          if (expectation.expected) {
            // Project expects knowledge - provide contextual setup prompt
            let setupText = `No knowledge found for "${query}".\n\n`;
            setupText += `**This project expects team knowledge** but it's not configured on this machine.\n`;
            setupText += `Signals: ${expectation.signals.join(', ')}\n\n`;

            if (teamDetection.teamRepoUrl) {
              setupText += `**Team repository detected:** \`${teamDetection.teamRepoUrl}\`\n\n`;
              setupText += `Run \`/knowledge-copilot\` to set up team knowledge (it will offer to clone the repository for you).\n`;
            } else {
              setupText += `Run \`/knowledge-copilot\` and choose "Join Team" to connect to your team's knowledge repository.\n`;
            }

            return {
              content: [{
                type: 'text',
                text: setupText
              }]
            };
          }

          // No expectation - standard message
          return {
            content: [{
              type: 'text',
              text: `No knowledge repository loaded.\n\n**To enable knowledge search:**\n1. Create a global knowledge repo at \`${globalPath}\` with a \`knowledge-manifest.json\`\n2. Or set \`KNOWLEDGE_REPO_PATH\` in .mcp.json for project-specific knowledge\n\nSee EXTENSION-SPEC.md for details.`
            }]
          };
        }

        const options: KnowledgeSearchOptions = {
          limit: a.limit as number | undefined,
          directory: a.directory as string | undefined,
          includeContent: a.includeContent as boolean | undefined
        };

        const results = knowledgeRepo.searchKnowledge(query, options);

        if (results.length === 0) {
          return {
            content: [{
              type: 'text',
              text: `No knowledge found for query: "${query}"\n\nTry different search terms or check your knowledge repository structure.`
            }]
          };
        }

        // Format results
        let output = `## Knowledge Search Results for "${query}"\n\n`;
        output += `Found ${results.length} result(s):\n\n`;

        for (const result of results) {
          output += `### ${result.name}\n`;
          output += `**Path:** \`${result.path}\`\n`;
          output += `**Source:** ${result.source} | **Relevance:** ${(result.relevance * 100).toFixed(0)}%\n`;
          if (result.section) {
            output += `**Section:** ${result.section}\n`;
          }
          output += '\n';

          if (result.content) {
            // Full content mode
            output += '```markdown\n' + result.content + '\n```\n\n';
          } else {
            // Snippet mode
            output += '> ' + result.snippet.replace(/\n/g, '\n> ') + '\n\n';
          }

          output += '---\n\n';
        }

        output += `Use \`knowledge_get(path)\` to retrieve full file content.`;

        return { content: [{ type: 'text', text: output }] };
      }

      case 'knowledge_get': {
        if (!knowledgeRepo.isLoaded()) {
          const status = knowledgeRepo.getStatus();
          const globalPath = status.global?.path || '~/.claude/knowledge';
          return {
            content: [{
              type: 'text',
              text: `No knowledge repository loaded.\n\n**To enable knowledge access:**\n1. Create a global knowledge repo at \`${globalPath}\` with a \`knowledge-manifest.json\`\n2. Or set \`KNOWLEDGE_REPO_PATH\` in .mcp.json for project-specific knowledge`
            }]
          };
        }

        const filePath = a.path as string;
        const result = knowledgeRepo.getKnowledgeFile(filePath);

        if (!result) {
          return {
            content: [{
              type: 'text',
              text: `Knowledge file not found: ${filePath}\n\nUse \`knowledge_search\` to find available files.`
            }]
          };
        }

        return {
          content: [{
            type: 'text',
            text: `# ${filePath}\n\n**Source:** ${result.source}\n**Path:** ${result.absolutePath}\n\n---\n\n${result.content}`
          }]
        };
      }

      case 'skill_evaluate': {
        const files = a.files as string[] | undefined;
        const text = a.text as string | undefined;
        const recentActivity = a.recentActivity as string[] | undefined;
        const threshold = a.threshold as number | undefined;
        const limit = a.limit as number | undefined;
        const showDetails = a.showDetails as boolean | undefined;

        if (!files && !text) {
          return {
            content: [{
              type: 'text',
              text: 'Error: Must provide either "files" or "text" parameter for skill evaluation.'
            }],
            isError: true
          };
        }

        // Build skills map from local provider
        const skillsList = local.listSkills();
        if (!skillsList.success || !skillsList.data || skillsList.data.length === 0) {
          return {
            content: [{
              type: 'text',
              text: 'No skills available for evaluation. Add skills to .claude/skills or ~/.claude/skills.'
            }]
          };
        }

        // Convert to map and set in evaluator
        const skillsMap = new Map<string, SkillMeta>();
        for (const skill of skillsList.data) {
          skillsMap.set(skill.name, skill);
        }
        skillEvaluator.setSkills(skillsMap);

        // Build evaluation context
        const context: EvaluationContext = {
          files,
          text,
          recentActivity,
        };

        // Run evaluation
        const results = skillEvaluator.evaluate(context, {
          threshold: threshold ?? 0.3,
          limit: limit ?? 10,
        });

        // Format and return results
        const output = formatEvaluationResults(results, showDetails ?? false);

        return {
          content: [{ type: 'text', text: output }]
        };
      }

      default:
        return {
          content: [{ type: 'text', text: `Unknown tool: ${name}` }],
          isError: true
        };
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return {
      content: [{ type: 'text', text: `Error: ${message}` }],
      isError: true
    };
  }
});

// Start server
async function main() {
  // Connect to Postgres if configured
  if (postgres) {
    const connected = await postgres.connect();
    if (config.logLevel === 'debug') {
      console.error(`Postgres: ${connected ? 'connected' : 'failed to connect'}`);
    }
  }

  if (config.logLevel === 'debug') {
    console.error('Skills Hub server starting...');
    console.error(`SkillsMP: ${skillsmp ? 'configured' : 'not configured'}`);
    console.error(`Local skills: ${local.getCount()} found (${local.getDiscoveredCount()} auto-discovered)`);
    console.error(`Cache: ${cache.getStats().total} entries`);
    const repoStatus = knowledgeRepo.getStatus();
    if (repoStatus.global) {
      console.error(`Knowledge repo (global): ${repoStatus.global.loaded ? repoStatus.global.manifest?.name : repoStatus.global.error}`);
    }
    if (repoStatus.project) {
      console.error(`Knowledge repo (project): ${repoStatus.project.loaded ? repoStatus.project.manifest?.name : repoStatus.project.error}`);
    }
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);

  if (config.logLevel === 'debug') {
    console.error('Skills Hub server running');
  }
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});

// Cleanup on exit
process.on('SIGINT', () => {
  cache.close();
  postgres?.close();
  process.exit(0);
});

process.on('SIGTERM', () => {
  cache.close();
  postgres?.close();
  process.exit(0);
});
