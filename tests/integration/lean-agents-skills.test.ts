/**
 * Integration Tests: Lean Agent Model + Skills System
 *
 * Tests the complete lean agent refactoring and skill integration:
 * 1. Agent structure validation (lean ~60-100 lines)
 * 2. Skill loading protocol in agents
 * 3. Skill template structure (quality sections)
 * 4. skill_evaluate auto-detection
 *
 * @see PRD-58bb45d1-f5eb-4e23-8e4a-2f386a955630
 * @see Stream-A (Skill Infrastructure)
 * @see Stream-C through Stream-I (Agent Refactoring)
 * @see Stream-Z (Integration)
 */

import { readFileSync, readdirSync, existsSync, statSync } from 'fs';
import { join, basename, relative } from 'path';

// ============================================================================
// TEST FRAMEWORK
// ============================================================================

interface TestResult {
  testName: string;
  status: 'PASS' | 'FAIL' | 'SKIP';
  duration: number;
  error?: string;
  details?: string;
}

const results: TestResult[] = [];

function logResult(testName: string, status: 'PASS' | 'FAIL' | 'SKIP', duration: number, error?: string, details?: string) {
  results.push({ testName, status, duration, error, details });
  const emoji = status === 'PASS' ? '✅' : status === 'FAIL' ? '❌' : '⏭️';
  console.log(`${emoji} ${testName} (${duration}ms)${error ? ': ' + error : ''}`);
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

function assertEquals<T>(actual: T, expected: T, message: string): void {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

function assertInRange(actual: number, min: number, max: number, message: string): void {
  if (actual < min || actual > max) {
    throw new Error(`${message}: expected ${actual} to be between ${min} and ${max}`);
  }
}

function assertContains(text: string, substring: string, message: string): void {
  if (!text.includes(substring)) {
    throw new Error(`${message}: expected to contain "${substring}"`);
  }
}

async function runTest(testName: string, testFn: () => void | Promise<void>): Promise<void> {
  const start = Date.now();
  try {
    await testFn();
    logResult(testName, 'PASS', Date.now() - start);
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    logResult(testName, 'FAIL', Date.now() - start, errorMessage);
  }
}

// ============================================================================
// TEST PATHS
// ============================================================================

const projectRoot = join(__dirname, '../..');
const agentsDir = join(projectRoot, '.claude/agents');
const skillsDir = join(projectRoot, '.claude/skills');
const templatesDir = join(projectRoot, 'templates');

// Lean agents (refactored in this initiative)
// Note: 'ta' is excluded because it's the orchestrating agent with different structure
const LEAN_AGENTS = ['me', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw'];

// Orchestrating agent (different structure - handles PRD/task creation)
const ORCHESTRATOR_AGENTS = ['ta'];

// Legacy agents (not refactored)
const LEGACY_AGENTS = ['cco', 'kc'];

// Skill categories
const SKILL_CATEGORIES = ['code', 'testing', 'security', 'documentation', 'devops'];

// The skill system expanded beyond code-pattern skills (commit 7facb21 "add
// sales role skills") to role-workflow and creative-reference domains that
// don't fit a code GOOD/BAD-example shape. Derive a skill's top-level
// category from its path (skill files no longer carry a skill_category:
// frontmatter field -- see the frontmatter test below) so the code-pattern
// quality checks can be scoped to the domains they actually apply to.
function skillCategoryOf(skillFile: string): string {
  const relative = skillFile.slice(skillsDir.length + 1);
  return relative.split('/')[0];
}

// Pure role-workflow skills (sales playbooks): no code, no GOOD/BAD or
// Pattern/Anti-Pattern content by design -- they're process guides.
const PROCESS_SKILL_CATEGORIES = ['sales'];

// Visual/creative reference skills (named palettes, curated pairings,
// evaluation rubrics): no code examples by design.
const REFERENCE_ONLY_SKILL_CATEGORIES = ['design'];

// ============================================================================
// AGENT STRUCTURE TESTS
// ============================================================================

async function testAgentStructure() {
  console.log('\n📦 Testing Agent Structure...\n');

  // Test: All lean agents exist
  await runTest('All lean agents exist', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      assert(existsSync(agentPath), `Agent ${agent}.md not found`);
    }
  });

  // Test: Lean agents are within line limit
  // Note: Domain agents (sd, uxd, uids, cw) have specification workflow sections
  // (~50 lines each). The 250-line cap also predates two later, framework-wide,
  // FF8/FF10-enforced additions to every agent file: the canonical Output
  // Contract block (.claude/agents/_shared/output-contract.md) and Runtime
  // Precedence block (.claude/agents/_shared/precedence.md). Current largest
  // lean agent (uids.md, richest domain content) is 360 lines; 400 keeps the
  // same "cap = current max + headroom" spirit as the old 250 did for its era.
  await runTest('Lean agents are within line limit', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');
      const lineCount = content.split('\n').length;

      assertInRange(lineCount, 40, 400, `Agent ${agent}.md has ${lineCount} lines`);
    }
  });

  // Test: Agents have required frontmatter
  await runTest('Agents have required frontmatter', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      // Check frontmatter markers
      assert(content.startsWith('---'), `Agent ${agent} missing opening frontmatter`);
      const secondDash = content.indexOf('---', 3);
      assert(secondDash > 0, `Agent ${agent} missing closing frontmatter`);

      // Extract frontmatter
      const frontmatter = content.slice(3, secondDash);

      // Check required fields
      assertContains(frontmatter, 'name:', `Agent ${agent} missing name`);
      assertContains(frontmatter, 'description:', `Agent ${agent} missing description`);
      assertContains(frontmatter, 'tools:', `Agent ${agent} missing tools`);
      assertContains(frontmatter, 'model:', `Agent ${agent} missing model`);
    }
  });

  // Test: skill_evaluate was a dead MCP tool name that never resolved to a
  // real, invokable tool -- deliberately purged from every agent's `tools:`
  // frontmatter (commit a978c8d "reduce framework context footprint", finished
  // by 209ad7c "purge retired-MCP refs"). Assert the retirement holds.
  await runTest('No agent tools frontmatter references skill_evaluate (retired MCP tool)', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      const toolsMatch = content.match(/tools:\s*(.+)/);
      assert(toolsMatch !== null, `Agent ${agent} missing tools`);

      const tools = toolsMatch[1];
      assert(!tools.includes('skill_evaluate'), `Agent ${agent} tools frontmatter still references retired skill_evaluate`);
    }
  });

  // Test: the old '## Skill Loading Protocol' section (a fictional
  // skill_evaluate() JS snippet) was removed in the same pass. Skill
  // discovery is now real: `cc skill search` (fallback keyword search) or a
  // mandatory `@include .claude/skills/...` for a domain-required skill
  // (e.g. sec's STRIDE+DREAD). Not every agent uses the same wording or a
  // dedicated heading, so assert the mechanism is documented in the body.
  await runTest('All agents document a real skill-discovery mechanism', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      const hasSkillDiscovery =
        content.includes('cc skill search') || content.includes('@include .claude/skills/');
      assert(
        hasSkillDiscovery,
        `Agent ${agent} missing a real skill-discovery mechanism (cc skill search or @include .claude/skills/)`
      );
    }
  });

  // Test: Agents have Core Behaviors section
  await runTest('Agents have Core Behaviors section', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, '## Core Behaviors', `Agent ${agent} missing Core Behaviors section`);
      assertContains(content, '**Always:**', `Agent ${agent} missing Always list`);
      assertContains(content, '**Never:**', `Agent ${agent} missing Never list`);
    }
  });

  // Test: Agents have Output Format section
  await runTest('Agents have Output Format section', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, '## Output Format', `Agent ${agent} missing Output Format section`);
    }
  });

  // Test: Agents have Route To Other Agent section
  await runTest('Agents have Route To Other Agent section', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, '## Route To Other Agent', `Agent ${agent} missing Route To Other Agent section`);
    }
  });

  // Test: Agents declare their known model tier.
  // v4.0.0 ("model-tier inversion") deliberately split lean agents by role:
  // strategy/creative agents (sd, uxd, uids, cw) run Opus; execution agents
  // (me, qa, sec, doc, do, uid) run Sonnet for cost efficiency. A blanket
  // "every lean agent is sonnet" assumption is stale post-inversion -- assert
  // the known-correct per-agent tier instead so a real drift (e.g. me
  // silently switching to opus) still fails this test.
  const EXPECTED_MODEL: Record<string, 'sonnet' | 'opus'> = {
    me: 'sonnet', qa: 'sonnet', sec: 'sonnet', doc: 'sonnet', do: 'sonnet', uid: 'sonnet',
    sd: 'opus', uxd: 'opus', uids: 'opus', cw: 'opus'
  };

  await runTest('Agents use their assigned model tier', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');
      const expected = EXPECTED_MODEL[agent];

      assertContains(content, `model: ${expected}`, `Agent ${agent} should use ${expected} model`);
    }
  });

  // Test: preflight_check was retired alongside skill_evaluate (same commits).
  await runTest('No agent tools frontmatter references preflight_check (retired MCP tool)', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      const toolsMatch = content.match(/tools:\s*(.+)/);
      assert(toolsMatch !== null, `Agent ${agent} missing tools`);

      const tools = toolsMatch[1];
      assert(!tools.includes('preflight_check'), `Agent ${agent} tools frontmatter still references retired preflight_check`);
    }
  });
}

// ============================================================================
// SKILL STRUCTURE TESTS
// ============================================================================

async function testSkillStructure() {
  console.log('\n🎯 Testing Skill Structure...\n');

  // Test: Skills directory exists
  await runTest('Skills directory exists', () => {
    assert(existsSync(skillsDir), 'Skills directory not found');
  });

  // Test: Expected skill categories exist
  await runTest('Expected skill categories exist', () => {
    for (const category of SKILL_CATEGORIES) {
      const categoryPath = join(skillsDir, category);
      assert(existsSync(categoryPath), `Skill category ${category} not found`);
    }
  });

  // Test: Skills have required frontmatter.
  // Commit 7facb21 ("auto-firing frontmatter migration") replaced the old
  // custom schema (skill_name/skill_category/trigger_files/trigger_keywords)
  // with the native Claude Code shape Claude Code itself reads to decide
  // when to auto-fire a skill: name + a trigger-rich description. See
  // templates/skills/SKILL-TEMPLATE.md's own header comment ("Canonical
  // frontmatter shape: name + trigger-rich description"). Verified: all 37
  // current SKILL.md files carry name: and description:; none carry the old
  // fields any more.
  await runTest('Skills have required frontmatter', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const label = relative(skillsDir, skillFile);

      // Check frontmatter markers
      assert(content.startsWith('---'), `Skill ${label} missing opening frontmatter`);
      const secondDash = content.indexOf('---', 3);
      assert(secondDash > 0, `Skill ${label} missing closing frontmatter`);

      // Extract frontmatter
      const frontmatter = content.slice(3, secondDash);

      // Check required fields
      assertContains(frontmatter, 'name:', `Skill ${label} missing name`);
      assertContains(frontmatter, 'description:', `Skill ${label} missing description`);
    }
  });

  // Test: Skills have quality sections (patterns and anti-patterns).
  // The skill system now spans role-workflow skills (sales) alongside
  // code-pattern skills, so this is scoped off PROCESS_SKILL_CATEGORIES.
  // Quality-anchor vocabulary is broadened beyond generic Pattern/GOOD/BAD
  // wording to the domain-appropriate headings skill authors actually use
  // (Anti-Generic Rules/Bans, Anti-Slop Detector, Validation/Quality
  // Checklist) -- these are real, verified section headings in the current
  // skill corpus, not a loosened "always true" fallback.
  await runTest('Skills have quality sections', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      if (PROCESS_SKILL_CATEGORIES.includes(skillCategoryOf(skillFile))) continue;

      const content = readFileSync(skillFile, 'utf-8');
      const label = relative(skillsDir, skillFile);

      // Check for pattern-related content
      const hasPatterns = content.includes('## Pattern') ||
                          content.includes('## Core Pattern') ||
                          content.includes('GOOD:') ||
                          content.includes('# GOOD');

      const hasAntiPatterns = content.includes('Anti-Pattern') ||
                               content.includes('Anti-Generic') ||
                               content.includes('Anti-Slop') ||
                               content.includes('BAD:') ||
                               content.includes('# BAD');

      const hasChecklist = content.includes('Validation Checklist') ||
                            content.includes('Quality Checklist');

      assert(hasPatterns || hasAntiPatterns || hasChecklist, `Skill ${label} missing pattern/anti-pattern/checklist content`);
    }
  });

  // Test: Skills have code examples.
  // Scoped off REFERENCE_ONLY_SKILL_CATEGORIES and PROCESS_SKILL_CATEGORIES:
  // design reference skills (named palettes, curated pairings, evaluation
  // rubrics) and sales playbooks are legitimately code-free by design.
  await runTest('Skills have code examples', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const category = skillCategoryOf(skillFile);
      if (REFERENCE_ONLY_SKILL_CATEGORIES.includes(category) || PROCESS_SKILL_CATEGORIES.includes(category)) continue;

      const content = readFileSync(skillFile, 'utf-8');
      const label = relative(skillsDir, skillFile);

      // Check for code blocks
      const codeBlockCount = (content.match(/```/g) || []).length;
      assert(codeBlockCount >= 2, `Skill ${label} should have at least one code example (found ${codeBlockCount / 2} blocks)`);
    }
  });

  // Test: Skills have reasonable token estimates
  await runTest('Skills have reasonable token estimates', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = relative(skillsDir, skillFile);

      const tokenMatch = content.match(/token_estimate:\s*(\d+)/);
      if (tokenMatch) {
        const tokenEstimate = parseInt(tokenMatch[1], 10);
        // Skills should be under 3000 tokens for efficiency
        assertInRange(tokenEstimate, 100, 3000, `Skill ${name} token estimate ${tokenEstimate}`);
      }
    }
  });
}

// ============================================================================
// SKILL TEMPLATE TESTS
// ============================================================================

async function testSkillTemplate() {
  console.log('\n📄 Testing Skill Template...\n');

  const templatePath = join(templatesDir, 'skills/SKILL-TEMPLATE.md');

  // Test: Skill template exists
  await runTest('Skill template exists', () => {
    assert(existsSync(templatePath), 'SKILL-TEMPLATE.md not found');
  });

  // Test: Template has required structure.
  // skill_name/skill_category/trigger_files/trigger_keywords were replaced
  // by the native Claude Code frontmatter shape (name + description) in the
  // same 7facb21 migration -- see the template's own header comment. The
  // body sections (Core Patterns/Anti-Patterns/Validation Checklist) are
  // unchanged and still present.
  await runTest('Template has required structure', () => {
    const content = readFileSync(templatePath, 'utf-8');

    assertContains(content, 'name:', 'Template missing name field');
    assertContains(content, 'description:', 'Template missing description field');
    assertContains(content, '## Core Patterns', 'Template missing Core Patterns section');
    assertContains(content, '## Anti-Patterns', 'Template missing Anti-Patterns section');
    assertContains(content, '## Validation Checklist', 'Template missing Validation Checklist section');
  });

  // Test: Template documents native auto-firing discoverability.
  // quality_keywords:/tags: (old FTS5-index-era fields) are gone; discovery
  // now runs on name + a "trigger-rich" description (native auto-firing) with
  // allowed-tools: as the other real, current frontmatter field.
  await runTest('Template documents native auto-firing discoverability', () => {
    const content = readFileSync(templatePath, 'utf-8');

    assertContains(content, 'allowed-tools:', 'Template missing allowed-tools field');
    assertContains(content, 'trigger-rich', 'Template missing trigger-rich description guidance');
  });
}

// ============================================================================
// REFERENCE MODULE TESTS
// ============================================================================

async function testReferenceModule() {
  console.log('\n📚 Testing Reference Module...\n');

  const referencePath = join(templatesDir, 'references/REFERENCE-TEMPLATE.md');

  // Test: Reference template exists
  await runTest('Reference template exists', () => {
    assert(existsSync(referencePath), 'REFERENCE-TEMPLATE.md not found');
  });

  // Test: Reference template has required structure
  await runTest('Reference template has required structure', () => {
    const content = readFileSync(referencePath, 'utf-8');

    assertContains(content, 'module_name:', 'Template missing module_name field');
    assertContains(content, 'module_type:', 'Template missing module_type field');
    assertContains(content, '## Patterns', 'Template missing Patterns section');
    assertContains(content, '## Anti-Patterns', 'Template missing Anti-Patterns section');
    assertContains(content, '## Quick Reference', 'Template missing Quick Reference section');
  });
}

// ============================================================================
// SKILL EVALUATE INTEGRATION TESTS
// ============================================================================

async function testSkillEvaluateIntegration() {
  console.log('\n🔍 Testing skill_evaluate Integration...\n');

  // Test: Skills have trigger-rich descriptions.
  // This used to check the trigger_files:/trigger_keywords: array fields,
  // both retired by the 7facb21 migration -- since no current SKILL.md
  // carries either field, both `if (match)` guards were permanently false
  // and the test passed vacuously (zero assertions ever ran). Triggering now
  // runs on name + description (native auto-firing reads only those two
  // fields), so assert the description is long enough to actually be
  // "trigger-rich" per the template's own guidance, instead of silently
  // testing nothing.
  await runTest('Skills have trigger-rich descriptions', () => {
    const skillFiles = findSkillFiles(skillsDir);
    const MIN_DESCRIPTION_CHARS = 150;

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const label = relative(skillsDir, skillFile);

      const secondDash = content.indexOf('---', 3);
      const frontmatter = content.slice(3, secondDash);
      const descStart = frontmatter.indexOf('description:');
      assert(descStart >= 0, `Skill ${label} missing description in frontmatter`);

      // description's value runs until the next top-level (unindented) key
      const afterDesc = frontmatter.slice(descStart + 'description:'.length);
      const nextKeyMatch = afterDesc.match(/\n[a-zA-Z_-]+:/);
      const descriptionValue = (nextKeyMatch ? afterDesc.slice(0, nextKeyMatch.index) : afterDesc).trim();

      assert(
        descriptionValue.length >= MIN_DESCRIPTION_CHARS,
        `Skill ${label} description is only ${descriptionValue.length} chars (want >= ${MIN_DESCRIPTION_CHARS} to be trigger-rich)`
      );
    }
  });

  // Test: Agent skill references match available skills.
  // Previously vacuous in two independent ways: the heading regex looked for
  // inline text "Available <word> skills:" that never occurs (the real
  // markup is a "## Available Skills" heading), and even when matched, the
  // inner loop never called assert() at all -- just a comment saying "we're
  // lenient here". Rewritten to actually catch a real regression: a typo'd
  // or stale skill name in an agent's Available Skills table.
  await runTest('Agent skill references match available skills', () => {
    const availableSkills = findSkillNames(skillsDir);

    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      const skillsSection = content.match(/## Available Skills\n([\s\S]*?)(\n## |$)/);
      if (!skillsSection) continue; // not every agent has a dedicated table -- see skill-discovery mechanism test

      const skillRefs = skillsSection[1].match(/`([a-z][a-z0-9-]*)`/g) || [];
      for (const ref of skillRefs) {
        const skillName = ref.replace(/`/g, '');
        assert(
          availableSkills.has(skillName),
          `Agent ${agent} references skill \`${skillName}\` in its Available Skills table, but no skill named "${skillName}" exists under .claude/skills`
        );
      }
    }
  });
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function findSkillFiles(dir: string): string[] {
  const files: string[] = [];

  function walk(currentDir: string) {
    if (!existsSync(currentDir)) return;

    const entries = readdirSync(currentDir);
    for (const entry of entries) {
      const fullPath = join(currentDir, entry);
      const stat = statSync(fullPath);

      if (stat.isDirectory()) {
        // codex-copilot/ is Codex's own mirror namespace (its equivalent of
        // Claude Code's agents+commands, using the same SKILL.md filename
        // convention) -- not a Claude Code skill and not subject to this
        // corpus's quality contract. Same exclusion CLAUDE.md documents for
        // AGENTS.md ("consumed by a different harness").
        if (entry === 'codex-copilot') continue;
        walk(fullPath);
      } else if (entry === 'SKILL.md') {
        // Only actual skill definitions -- a skill directory can also carry
        // auxiliary docs (e.g. sales/create-an-asset/QUICKREF.md,
        // security/stride-dread/templates/threat-model.md) that have no
        // skill frontmatter at all and aren't themselves loadable skills.
        files.push(fullPath);
      }
    }
  }

  walk(dir);
  return files;
}

function findSkillNames(dir: string): Set<string> {
  const names = new Set<string>();
  const files = findSkillFiles(dir);

  for (const file of files) {
    const content = readFileSync(file, 'utf-8');
    // skill_name: was retired by the 7facb21 migration -- name: is the
    // current, native Claude Code field.
    const nameMatch = content.match(/^name:\s*([a-z0-9-]+)/m);
    if (nameMatch) {
      names.add(nameMatch[1]);
    }
  }

  return names;
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function main() {
  console.log('='.repeat(70));
  console.log('  LEAN AGENTS + SKILLS INTEGRATION TESTS');
  console.log('='.repeat(70));

  await testAgentStructure();
  await testSkillStructure();
  await testSkillTemplate();
  await testReferenceModule();
  await testSkillEvaluateIntegration();

  // Print summary
  console.log('\n' + '='.repeat(70));
  console.log('  TEST SUMMARY');
  console.log('='.repeat(70));

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  const skipped = results.filter(r => r.status === 'SKIP').length;

  console.log(`\n✅ Passed: ${passed}`);
  console.log(`❌ Failed: ${failed}`);
  console.log(`⏭️  Skipped: ${skipped}`);
  console.log(`📊 Total: ${results.length}`);

  if (failed > 0) {
    console.log('\n❌ FAILED TESTS:');
    for (const result of results.filter(r => r.status === 'FAIL')) {
      console.log(`  - ${result.testName}: ${result.error}`);
    }
    process.exit(1);
  } else {
    console.log('\n✅ ALL TESTS PASSED');
    process.exit(0);
  }
}

main().catch(console.error);
