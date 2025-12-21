# Technical Design: Knowledge Repository Extension Resolution

## Status
Proposed

## Context

The Claude Copilot framework provides base agents with generic methodologies. We need to enable knowledge repositories to extend these agents with company-specific content via:
- Override extensions (complete replacement)
- Extension files (section-based merging)
- Skills injection (capability enhancement)

This system must integrate into the existing skills-copilot MCP server architecture.

## Requirements Summary

### Functional Requirements
1. Discover knowledge repositories via `KNOWLEDGE_REPO_PATH` environment variable
2. Load and validate `knowledge-manifest.json` files
3. Provide MCP tools for extension resolution:
   - `extension_get(agent)` - Get resolved extension content for an agent
   - `extension_list()` - List all available extensions
   - `manifest_status()` - Get manifest validation status
4. Support three extension types: override, extension, skills
5. Handle missing required skills with fallback behaviors
6. Gracefully degrade when no knowledge repo exists

### Non-Functional Requirements
- Zero performance impact when no knowledge repo configured
- Fast resolution (cached manifest parsing)
- Clear error messages for misconfiguration
- Backward compatible with existing skills-copilot tools

---

## Proposed Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────┐
│ Claude invokes @agent-sd                    │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Agent loader checks for extensions          │
│ via extension_get(agent: "sd")              │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ KnowledgeRepoProvider                       │
│ 1. Check KNOWLEDGE_REPO_PATH env var        │
│ 2. Load knowledge-manifest.json             │
│ 3. Find extension for "sd"                  │
│ 4. Validate required skills                 │
│ 5. Apply extension type logic               │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Return resolved agent content:              │
│ - Override: Extension file only             │
│ - Extension: Merged base + extension        │
│ - Skills: Base + injected skills            │
│ - None: Base agent only                     │
└─────────────────────────────────────────────┘
```

### Component Integration

#### 1. New Provider: KnowledgeRepoProvider

**Location:** `/mcp-servers/skills-copilot/src/providers/knowledge-repo.ts`

**Responsibilities:**
- Discover knowledge repository from environment variable
- Load and cache manifest file
- Validate manifest against JSON schema
- Resolve extensions by agent ID
- Read extension files from knowledge repo
- Apply extension logic (override/extension/skills)
- Validate required skills availability

**Key Methods:**
```typescript
class KnowledgeRepoProvider {
  constructor(repoPath?: string)

  // Core resolution
  getExtension(agentId: string): ProviderResult<AgentExtension>
  listExtensions(): ProviderResult<ExtensionMeta[]>
  getManifestStatus(): ProviderResult<ManifestStatus>

  // Validation
  private validateManifest(manifest: unknown): ManifestValidationResult
  private checkRequiredSkills(extension: Extension): SkillCheckResult

  // File operations
  private loadManifest(): KnowledgeManifest | null
  private readExtensionFile(filePath: string): string
  private parseExtensionFrontmatter(content: string): ExtensionMeta

  // Caching
  private manifestCache: KnowledgeManifest | null
  private lastChecked: number
  refresh(): void
}
```

#### 2. New Types

**Location:** `/mcp-servers/skills-copilot/src/types.ts`

```typescript
// Extension types
export interface KnowledgeManifest {
  version: string;
  name: string;
  description?: string;
  framework?: {
    name: string;
    minVersion: string;
  };
  extensions?: Extension[];
  skills?: {
    local?: LocalSkill[];
    remote?: RemoteSkill[];
  };
  glossary?: string;
  config?: ManifestConfig;
}

export interface Extension {
  agent: AgentId;
  type: 'override' | 'extension' | 'skills';
  file: string;
  description?: string;
  requiredSkills?: string[];
  fallbackBehavior?: 'use_base' | 'use_base_with_warning' | 'fail';
}

export interface AgentExtension {
  agentId: AgentId;
  type: 'override' | 'extension' | 'skills' | 'base';
  content: string;
  source: 'base' | 'knowledge-repo';
  metadata?: {
    description?: string;
    requiredSkills?: string[];
    availableSkills?: string[];
    fallbackApplied?: boolean;
  };
}

export interface ExtensionMeta {
  agent: AgentId;
  type: 'override' | 'extension' | 'skills';
  description?: string;
  hasRequiredSkills: boolean;
  source: string; // file path relative to knowledge repo
}

export interface ManifestStatus {
  configured: boolean;
  repoPath?: string;
  manifestValid: boolean;
  manifestVersion?: string;
  extensionCount: number;
  validationErrors?: string[];
  glossaryPath?: string;
}

export type AgentId = 'me' | 'ta' | 'qa' | 'sec' | 'doc' | 'do' | 'sd' | 'uxd' | 'uids' | 'uid' | 'cw';

export interface SkillCheckResult {
  allAvailable: boolean;
  missing: string[];
  available: string[];
}

export interface ManifestValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}
```

#### 3. New MCP Tools

**Location:** `/mcp-servers/skills-copilot/src/index.ts`

```typescript
// Add to TOOLS array:
{
  name: 'extension_get',
  description: 'Get agent extension from knowledge repository. Returns base agent if no extension exists.',
  inputSchema: {
    type: 'object',
    properties: {
      agent: {
        type: 'string',
        enum: ['me', 'ta', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw'],
        description: 'Agent ID to get extension for'
      }
    },
    required: ['agent']
  }
},
{
  name: 'extension_list',
  description: 'List all agent extensions available in knowledge repository',
  inputSchema: {
    type: 'object',
    properties: {}
  }
},
{
  name: 'manifest_status',
  description: 'Get knowledge repository manifest status and configuration',
  inputSchema: {
    type: 'object',
    properties: {}
  }
}
```

#### 4. Extension Resolution Algorithm

**Override Type:**
```typescript
async function resolveOverride(extension: Extension, baseContent: string): Promise<string> {
  // 1. Check required skills
  const skillCheck = await checkRequiredSkills(extension.requiredSkills);

  if (!skillCheck.allAvailable) {
    return applyFallback(extension.fallbackBehavior, baseContent, skillCheck.missing);
  }

  // 2. Read override file
  const overrideContent = readExtensionFile(extension.file);

  // 3. Return override content (replaces base entirely)
  return overrideContent;
}
```

**Extension Type:**
```typescript
async function resolveExtension(extension: Extension, baseContent: string): Promise<string> {
  // 1. Check required skills
  const skillCheck = await checkRequiredSkills(extension.requiredSkills);

  if (!skillCheck.allAvailable) {
    return applyFallback(extension.fallbackBehavior, baseContent, skillCheck.missing);
  }

  // 2. Read extension file
  const extensionContent = readExtensionFile(extension.file);

  // 3. Parse frontmatter to get overrideSections
  const meta = parseExtensionFrontmatter(extensionContent);

  // 4. Merge: Replace specified sections, keep others from base
  return mergeSections(baseContent, extensionContent, meta.overrideSections);
}
```

**Skills Type:**
```typescript
async function resolveSkills(extension: Extension, baseContent: string): Promise<string> {
  // 1. Load skills injection file
  const skillsConfig = JSON.parse(readExtensionFile(extension.file));

  // 2. Build skills section
  const skillsSection = buildSkillsSection(skillsConfig.skills);

  // 3. Inject into base agent's "Available Skills" section
  return injectSkillsSection(baseContent, skillsSection);
}
```

**Fallback Behavior:**
```typescript
function applyFallback(
  behavior: 'use_base' | 'use_base_with_warning' | 'fail',
  baseContent: string,
  missingSkills: string[]
): string {
  switch (behavior) {
    case 'fail':
      throw new Error(`Required skills unavailable: ${missingSkills.join(', ')}`);

    case 'use_base_with_warning':
      const warning = `\n\n> **Warning:** This agent has company-specific extensions, but required skills are unavailable: ${missingSkills.join(', ')}. Using base agent instead.\n\n`;
      return warning + baseContent;

    case 'use_base':
    default:
      return baseContent;
  }
}
```

---

## Component Changes

| Component | Change | Rationale |
|-----------|--------|-----------|
| `skills-copilot/src/index.ts` | Add 3 new tools, integrate KnowledgeRepoProvider | Extension resolution needs MCP interface |
| `skills-copilot/src/types.ts` | Add extension-related types | Type safety for manifest and extensions |
| `skills-copilot/src/providers/knowledge-repo.ts` | New provider class | Encapsulate knowledge repo logic |
| `skills-copilot/src/providers/index.ts` | Export new provider | Standard provider pattern |
| `templates/mcp.json` | Add KNOWLEDGE_REPO_PATH env var (optional) | User configuration point |
| `.claude/agents/*.md` | No changes | Agents remain backward compatible |

---

## Data Model Changes

### Environment Variables

```bash
# New optional variable for skills-copilot server
KNOWLEDGE_REPO_PATH="/path/to/company-knowledge-repo"
```

### File Structure

**Knowledge Repository:**
```
company-knowledge-repo/
├── knowledge-manifest.json     # REQUIRED
├── .claude/
│   └── extensions/
│       ├── sd.override.md      # Override example
│       ├── uxd.extension.md    # Extension example
│       └── ta.skills.json      # Skills injection
├── skills/
│   ├── moments-mapping.md
│   └── api-standards.md
└── docs/
    └── glossary.md
```

---

## API Changes

### New MCP Tools

#### extension_get

**Request:**
```json
{
  "name": "extension_get",
  "arguments": {
    "agent": "sd"
  }
}
```

**Response (when extension exists):**
```json
{
  "content": [{
    "type": "text",
    "text": "# Agent Extension: sd\n\n**Type:** override\n**Source:** company-knowledge-repo\n**Required Skills:** moments-mapping, forces-analysis\n\n---\n\n[Full agent content here]"
  }]
}
```

**Response (when no extension):**
```json
{
  "content": [{
    "type": "text",
    "text": "[Base agent content from .claude/agents/sd.md]"
  }]
}
```

#### extension_list

**Response:**
```json
{
  "content": [{
    "type": "text",
    "text": "## Available Agent Extensions\n\n| Agent | Type | Description | Required Skills Available |\n|-------|------|-------------|---------------------------|\n| sd | override | Moments Framework | Yes |\n| uxd | extension | Design system integration | Yes |\n| ta | skills | Architecture patterns | N/A |"
  }]
}
```

#### manifest_status

**Response:**
```json
{
  "content": [{
    "type": "text",
    "text": "{\n  \"configured\": true,\n  \"repoPath\": \"/path/to/repo\",\n  \"manifestValid\": true,\n  \"manifestVersion\": \"1.0\",\n  \"extensionCount\": 3,\n  \"glossaryPath\": \"docs/glossary.md\"\n}"
  }]
}
```

---

## Security Considerations

### Path Traversal Prevention
- Validate all file paths from manifest
- Ensure paths are relative and within knowledge repo
- Reject paths with `..` or absolute paths

```typescript
function validateFilePath(repoPath: string, relativePath: string): string {
  // Reject absolute paths
  if (path.isAbsolute(relativePath)) {
    throw new Error('Absolute paths not allowed in manifest');
  }

  // Reject parent directory traversal
  if (relativePath.includes('..')) {
    throw new Error('Parent directory references not allowed');
  }

  // Resolve and ensure within repo
  const fullPath = path.resolve(repoPath, relativePath);
  const normalizedRepo = path.resolve(repoPath);

  if (!fullPath.startsWith(normalizedRepo)) {
    throw new Error('Path escapes knowledge repository');
  }

  return fullPath;
}
```

### Input Validation
- Validate manifest against JSON schema
- Sanitize agent IDs (enum validation)
- Limit file size reads (prevent DoS)
- Validate extension file frontmatter

### Access Control
- Read-only access to knowledge repo
- No write operations
- No code execution from manifest
- Content treated as data, not code

---

## Performance Considerations

### Caching Strategy
1. **Manifest cache:** Load once, cache for session
2. **Extension content cache:** Cache resolved extensions by agent ID
3. **File reading:** Read extension files on-demand, cache result
4. **Skill availability cache:** Cache skill checks to avoid repeated DB queries

### Expected Load
- Manifest load: Once per MCP server start (or on refresh)
- Extension resolution: Once per agent invocation (with cache)
- File I/O: Minimal, only for extension files (typically <50KB each)

### Optimizations
```typescript
class KnowledgeRepoProvider {
  private manifestCache: KnowledgeManifest | null = null;
  private extensionContentCache: Map<string, string> = new Map();
  private skillCheckCache: Map<string, SkillCheckResult> = new Map();
  private manifestLastLoaded: number = 0;
  private CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

  private getManifest(): KnowledgeManifest | null {
    const now = Date.now();

    // Return cached if fresh
    if (this.manifestCache && (now - this.manifestLastLoaded) < this.CACHE_TTL_MS) {
      return this.manifestCache;
    }

    // Reload and cache
    this.manifestCache = this.loadManifest();
    this.manifestLastLoaded = now;
    return this.manifestCache;
  }
}
```

### Bottlenecks
- File I/O for large extension files (mitigated by caching)
- Skill availability checks (mitigated by caching skill_list results)
- Manifest parsing (mitigated by single load + cache)

---

## Testing Strategy

### Unit Tests

**KnowledgeRepoProvider:**
- Manifest loading and parsing
- Extension resolution (all three types)
- Fallback behavior application
- Path validation
- Cache behavior
- Skill availability checks

**Test Cases:**
```typescript
describe('KnowledgeRepoProvider', () => {
  describe('getExtension', () => {
    it('returns base agent when no manifest exists')
    it('returns base agent when agent has no extension')
    it('returns override content when extension type is override')
    it('merges extension sections when type is extension')
    it('injects skills when type is skills')
    it('applies fallback when required skills missing')
    it('throws error when fallback is "fail" and skills missing')
  })

  describe('validateManifest', () => {
    it('validates correct manifest schema')
    it('rejects invalid version')
    it('rejects invalid agent IDs')
    it('rejects invalid extension types')
    it('rejects path traversal attempts')
  })

  describe('caching', () => {
    it('caches manifest after first load')
    it('refreshes manifest after TTL expires')
    it('caches extension content by agent ID')
  })
})
```

### Integration Tests

1. **End-to-end extension resolution:**
   - Create test knowledge repo with all extension types
   - Invoke `extension_get` for each agent
   - Verify correct content returned

2. **Skills integration:**
   - Test with skills available in local/postgres/skillsmp
   - Verify skill availability checks work across providers

3. **Error handling:**
   - Invalid manifest JSON
   - Missing extension files
   - Malformed extension frontmatter

### Manual Testing

1. Create sample knowledge repository
2. Configure `KNOWLEDGE_REPO_PATH`
3. Invoke agents via Claude Code
4. Verify extensions applied correctly
5. Test fallback scenarios

---

## Rollout Plan

### Phase 1: Core Provider (Week 1)
**Goal:** Basic extension resolution without skill validation

**Tasks:**
- [ ] Create `KnowledgeRepoProvider` class
- [ ] Implement manifest loading and validation
- [ ] Implement override extension type
- [ ] Add `extension_get` MCP tool
- [ ] Add `manifest_status` MCP tool
- [ ] Unit tests for core functionality

**Deliverable:** Override extensions work, no skill validation yet

**Risk:** None (additive feature, backward compatible)

### Phase 2: Extension Types (Week 2)
**Goal:** Support all three extension types

**Tasks:**
- [ ] Implement extension type (section merging)
- [ ] Implement skills type (skills injection)
- [ ] Add `extension_list` MCP tool
- [ ] Section parsing logic
- [ ] JSON parsing for skills files
- [ ] Unit tests for merging/injection

**Deliverable:** All extension types functional

**Risk:** Low (self-contained logic)

### Phase 3: Skill Validation (Week 3)
**Goal:** Required skills validation and fallback behavior

**Tasks:**
- [ ] Integrate with existing skill providers
- [ ] Implement skill availability checks
- [ ] Implement fallback behavior logic
- [ ] Cache skill checks
- [ ] Error handling for missing skills
- [ ] Integration tests with skill providers

**Deliverable:** Full fallback behavior support

**Risk:** Medium (depends on skill provider integration)

### Phase 4: Documentation & Polish (Week 4)
**Goal:** Production-ready with docs

**Tasks:**
- [ ] Update CLAUDE.md with extension usage
- [ ] Create knowledge repo setup guide
- [ ] Add examples to templates/
- [ ] Performance profiling and optimization
- [ ] Security audit (path validation)
- [ ] Integration testing with real knowledge repos

**Deliverable:** Production-ready feature

**Risk:** Low (polish phase)

### Rollback Strategy

**If issues arise:**
1. Feature is opt-in via `KNOWLEDGE_REPO_PATH` environment variable
2. No environment variable = no extension resolution (falls back to base agents)
3. Existing functionality unchanged (skills-copilot still works as before)
4. Can disable by removing environment variable from MCP config

**Monitoring:**
- Log extension resolution attempts
- Track fallback behavior triggers
- Monitor file I/O performance
- Alert on manifest validation failures

---

## Open Questions

### 1. Should we support multiple knowledge repositories?

**Current design:** Single `KNOWLEDGE_REPO_PATH`

**Alternative:** Support comma-separated paths or array in config

**Recommendation:** Start with single repo. Add multi-repo support later if needed.

**Rationale:** YAGNI - most organizations will have one canonical knowledge repo

---

### 2. How should we handle glossary injection?

**Current spec:** Manifest has optional `glossary` field pointing to markdown file

**Options:**
a. Inject glossary at top of every extended agent
b. Provide separate `glossary_get` tool
c. Auto-inject only when extension exists

**Recommendation:** Option C - auto-inject glossary content into extended agents only

**Rationale:** Keeps glossary context-relevant, doesn't bloat base agents

---

### 3. Should extension resolution be synchronous or cached at startup?

**Current design:** Load manifest on first `extension_get` call, cache for session

**Alternative:** Pre-load all extensions at MCP server startup

**Recommendation:** Keep lazy loading with caching

**Rationale:**
- Faster server startup
- Only loads what's needed
- Cache provides performance benefit
- Easier to refresh without server restart

---

### 4. How do we version extensions for compatibility?

**Current spec:** `framework.minVersion` in manifest validates framework compatibility

**Question:** Should extensions have their own version numbers?

**Recommendation:** Add optional `version` field to Extension type

**Rationale:** Allows tracking extension changes independently from manifest version

```json
{
  "agent": "sd",
  "type": "override",
  "file": ".claude/extensions/sd.override.md",
  "version": "2.1.0",  // Optional
  "description": "Moments Framework v2"
}
```

---

### 5. Should we support remote knowledge repositories?

**Current design:** Local filesystem only

**Alternative:** Support `git://`, `https://`, `s3://` URIs

**Recommendation:** Phase 2+ feature, not MVP

**Rationale:**
- Adds complexity (authentication, caching, sync)
- Local repos can be git-synced by users
- Remote support can be added later without breaking changes

---

## Quality Gates

- [x] Requirements fully understood
- [x] Existing system impact assessed (additive, no breaking changes)
- [x] Multiple options considered (see Open Questions)
- [x] Trade-offs documented (caching strategy, phased rollout)
- [x] Security implications addressed (path validation, read-only access)
- [x] Scalability considered (caching strategy, lazy loading)
- [x] Incremental delivery possible (4-phase rollout plan)
- [x] Rollback strategy defined (env var opt-in, backward compatible)

---

## Decision Authority

**This design requires approval from:**
- Framework maintainers (architectural changes to skills-copilot)
- Security review (file path validation)

**Can proceed autonomously with:**
- Provider implementation details
- Caching strategy specifics
- Unit test structure

---

## Alternatives Considered

### Alternative 1: Separate MCP Server

**Approach:** Create new `knowledge-copilot` MCP server instead of extending `skills-copilot`

**Pros:**
- Cleaner separation of concerns
- Independent deployment

**Cons:**
- Requires two MCP servers configured
- Duplicates provider infrastructure
- Skills-copilot already has skill resolution logic needed for validation

**Decision:** Rejected - skills-copilot is the natural home for this feature

---

### Alternative 2: Agent File Overrides via Filesystem

**Approach:** Instead of MCP tools, allow users to drop extension files in `.claude/agents/` directly

**Pros:**
- Simpler implementation
- No MCP server changes needed

**Cons:**
- No skill validation possible
- No fallback behavior
- Breaks separation between framework and knowledge repo
- Users must manually manage file conflicts

**Decision:** Rejected - violates framework/extension separation principle

---

### Alternative 3: Runtime Agent Composition

**Approach:** Build agents dynamically by composing markdown sections at runtime

**Pros:**
- Maximum flexibility
- Could mix multiple extensions

**Cons:**
- Complex merging logic
- Hard to debug
- Performance overhead
- Unclear precedence rules

**Decision:** Rejected - over-engineered for current needs

---

## Success Metrics

**Feature is successful when:**

1. **Adoption:** 3+ knowledge repositories using extension system
2. **Performance:** Extension resolution <50ms (cached)
3. **Reliability:** Zero path traversal vulnerabilities found
4. **Usability:** Users can set up knowledge repo in <15 minutes
5. **Compatibility:** Works with all 11 base agents without modification

---

## Next Steps

1. **Review this design** with framework maintainers
2. **Address open questions** (prioritize questions 2 and 4)
3. **Create task breakdown** for Phase 1 implementation
4. **Set up test knowledge repository** for integration testing
5. **Begin Phase 1 implementation** after approval

---

## Appendix A: Example Extension Files

### Override Example

**File:** `.claude/extensions/sd.override.md`

```markdown
---
extends: sd
type: override
description: Moments Framework methodology for service design
requiredSkills:
  - moments-mapping
  - forces-analysis
fallback: use_base_with_warning
---

# Service Designer — System Instructions (Moments Framework)

## Identity

**Role:** Service Designer / Experience Architect

**Mission:** Design end-to-end service experiences using the Moments Framework...

[Complete replacement of base agent]
```

### Extension Example

**File:** `.claude/extensions/uxd.extension.md`

```markdown
---
extends: uxd
type: extension
description: Acme Corp design system integration
overrideSections:
  - Design System
  - Component Library
preserveSections:
  - Core Methodologies
  - Quality Gates
---

# UX Designer Extensions

## Design System

**Acme Design System v3.0**

Before creating any new components, search the Figma design system library...

## Component Library

All designs must reference these components:
- Navigation: TopNav, SideNav, Breadcrumbs
- Forms: Input, Select, Checkbox, Radio
- Feedback: Alert, Toast, Modal
...
```

### Skills Example

**File:** `.claude/extensions/ta.skills.json`

```json
{
  "extends": "ta",
  "type": "skills",
  "description": "Architecture patterns and API standards",
  "skills": [
    {
      "name": "architecture-patterns",
      "source": "local",
      "path": "skills/architecture-patterns.md",
      "whenToUse": "When designing new services or features",
      "priority": "required"
    },
    {
      "name": "api-standards",
      "source": "local",
      "path": "skills/api-standards.md",
      "whenToUse": "When creating API endpoints",
      "priority": "required"
    }
  ]
}
```

---

## Appendix B: Manifest Validation Rules

### Required Fields
- `version` (must be "1.0")
- `name` (non-empty string)

### Optional Fields
- `description` (string)
- `framework.name` (must be "claude-copilot" if present)
- `framework.minVersion` (semver string if present)
- `extensions` (array of Extension objects)
- `skills.local` (array of LocalSkill objects)
- `skills.remote` (array of RemoteSkill objects)
- `glossary` (relative path string)
- `config` (object)

### Extension Object Validation
- `agent` (must be valid AgentId enum value)
- `type` (must be "override" | "extension" | "skills")
- `file` (relative path, no `..`, no absolute paths)
- `fallbackBehavior` (must be "use_base" | "use_base_with_warning" | "fail" if present)
- `requiredSkills` (array of strings if present)

### File Path Validation
```typescript
function isValidRelativePath(path: string): boolean {
  // Must not be absolute
  if (path.startsWith('/')) return false;

  // Must not contain parent directory references
  if (path.includes('..')) return false;

  // Must not be empty
  if (path.trim() === '') return false;

  return true;
}
```

---

**Author:** Tech Architect Agent
**Date:** 2025-12-21
**Status:** Awaiting Review
