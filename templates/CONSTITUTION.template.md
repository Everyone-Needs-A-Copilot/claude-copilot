# Project Constitution

---
version: "1.0"
project: "{{PROJECT_NAME}}"
lastUpdated: "{{YYYY-MM-DD}}"
---

This document defines non-negotiable rules, constraints, and decision authority for this project. It serves as the foundation for AI-assisted development, ensuring all code, architecture, and decisions align with project requirements.

---

## Project Identity

### Mission
<!-- What is the core purpose of this project? What problem does it solve? -->
{{PROJECT_MISSION}}

### Core Values
<!-- What principles guide all decisions? (e.g., security-first, user privacy, performance, accessibility) -->
- {{VALUE_1}}
- {{VALUE_2}}
- {{VALUE_3}}

---

## Technical Constraints

### Non-Negotiable Rules
<!-- Rules that MUST NEVER be violated. Examples: -->
<!-- - All user data must be encrypted at rest -->
<!-- - No external API calls without timeout/retry logic -->
<!-- - All public endpoints require authentication -->
<!-- - Zero tolerance for SQL injection vulnerabilities -->

1. {{CONSTRAINT_1}}
2. {{CONSTRAINT_2}}
3. {{CONSTRAINT_3}}

### Technology Stack
<!-- Core technologies that define this project -->
- **Language:** {{PRIMARY_LANGUAGE}}
- **Framework:** {{FRAMEWORK}}
- **Database:** {{DATABASE}}
- **Infrastructure:** {{INFRASTRUCTURE}}

### Prohibited Patterns
<!-- Anti-patterns or technologies explicitly banned from this codebase -->
<!-- Examples: -->
<!-- - No direct DOM manipulation (use framework) -->
<!-- - No synchronous file I/O in request handlers -->
<!-- - No shared mutable state between requests -->

- {{PROHIBITED_1}}
- {{PROHIBITED_2}}

---

## Decision Authority

### Approval Required
<!-- Decisions that require human approval before implementation -->

| Decision Type | Approver | Examples |
|---------------|----------|----------|
| Architecture changes | {{ARCHITECT_ROLE}} | New service, database migration, API redesign |
| Security changes | {{SECURITY_ROLE}} | Auth flow, encryption, permissions |
| Database schema | {{DBA_ROLE}} | Schema changes, migrations |
| Dependencies | {{TECH_LEAD_ROLE}} | New package, version upgrades |
| {{CUSTOM_DECISION}} | {{CUSTOM_ROLE}} | {{CUSTOM_EXAMPLES}} |

### Agent Authority
<!-- Decisions agents can make autonomously -->

- **@agent-me** can: Implement features within existing patterns, refactor without changing behavior
- **@agent-qa** can: Add tests, fix test failures, update test data
- **@agent-doc** can: Update documentation, add code comments, create API docs
- **{{CUSTOM_AGENT}}** can: {{CUSTOM_AUTHORITY}}

---

## Quality Standards

### Acceptance Criteria
<!-- What must be true for code to be considered "done"? -->

- [ ] All tests pass (unit, integration, e2e)
- [ ] Code coverage >= {{COVERAGE_THRESHOLD}}%
- [ ] Linter passes with zero errors
- [ ] Security scan shows no critical/high vulnerabilities
- [ ] Performance budget met ({{PERFORMANCE_METRIC}})
- [ ] Accessibility standards met ({{ACCESSIBILITY_STANDARD}})
- [ ] {{CUSTOM_CRITERION}}

### Definition of Done
<!-- Checklist for feature completion -->

1. Functionality implemented per requirements
2. Tests written and passing
3. Documentation updated
4. Code reviewed (if applicable)
5. Deployed to staging
6. {{CUSTOM_STEP}}

---

## Optional Sections

<!-- Uncomment and customize sections relevant to your project -->

<!--
## Coding Standards

### Style Guide
- Follow {{STYLE_GUIDE_NAME}} (e.g., Airbnb JavaScript, Google Java)
- Use {{FORMATTING_TOOL}} for automatic formatting
- Max line length: {{MAX_LINE_LENGTH}}
- Indentation: {{INDENT_TYPE}} (spaces/tabs)

### Naming Conventions
- Files: {{FILE_NAMING}} (e.g., kebab-case, PascalCase)
- Functions: {{FUNCTION_NAMING}} (e.g., camelCase, snake_case)
- Constants: {{CONSTANT_NAMING}} (e.g., SCREAMING_SNAKE_CASE)
- Components: {{COMPONENT_NAMING}} (e.g., PascalCase)

### Code Organization
- {{ORGANIZATION_RULE_1}}
- {{ORGANIZATION_RULE_2}}
-->

<!--
## Architecture Principles

### Design Patterns
- Use {{PATTERN_1}} for {{USE_CASE_1}}
- Avoid {{ANTI_PATTERN}} because {{REASON}}

### Service Boundaries
- {{SERVICE_1}} handles {{RESPONSIBILITY_1}}
- {{SERVICE_2}} handles {{RESPONSIBILITY_2}}
- Cross-service communication via {{MECHANISM}}

### Data Flow
- {{DATA_FLOW_RULE_1}}
- {{DATA_FLOW_RULE_2}}
-->

<!--
## Security Requirements

### Authentication
- Mechanism: {{AUTH_MECHANISM}}
- Session duration: {{SESSION_DURATION}}
- MFA: {{MFA_POLICY}}

### Authorization
- Model: {{AUTHZ_MODEL}} (e.g., RBAC, ABAC)
- Default: {{DEFAULT_PERMISSION}} (deny-by-default)

### Data Protection
- PII handling: {{PII_POLICY}}
- Encryption: {{ENCRYPTION_STANDARD}}
- Secrets management: {{SECRETS_TOOL}}

### Compliance
- Standards: {{COMPLIANCE_STANDARDS}} (e.g., GDPR, HIPAA, SOC2)
- Audit logging: {{AUDIT_POLICY}}
-->

<!--
## Performance Budgets

### Response Times
- API endpoints: {{API_TARGET}} (e.g., p95 < 200ms)
- Page load: {{PAGE_LOAD_TARGET}} (e.g., LCP < 2.5s)
- Database queries: {{DB_QUERY_TARGET}} (e.g., < 100ms)

### Resource Limits
- Bundle size: {{BUNDLE_SIZE_LIMIT}} (e.g., < 250KB gzipped)
- Memory: {{MEMORY_LIMIT}} (e.g., < 512MB per instance)
- Database connections: {{DB_POOL_SIZE}}

### Scalability
- Target load: {{LOAD_TARGET}} (e.g., 10k req/sec)
- Horizontal scaling: {{SCALING_POLICY}}
-->

<!--
## Accessibility Requirements

### Standards
- Compliance level: {{WCAG_LEVEL}} (e.g., WCAG 2.1 AA)
- Testing tools: {{A11Y_TOOLS}} (e.g., axe, Lighthouse)

### Requirements
- All interactive elements keyboard-navigable
- Color contrast ratio >= {{CONTRAST_RATIO}}
- Screen reader compatible (test with {{SCREEN_READER}})
- Forms have proper labels and error messages
- {{CUSTOM_A11Y_REQUIREMENT}}
-->

---

## Revision History

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| {{YYYY-MM-DD}} | 1.0 | Initial constitution | {{AUTHOR}} |

---

**Note to AI Agents:** This Constitution overrides default behaviors. When in doubt, consult this document before making technical decisions. If a requirement conflicts with this Constitution, STOP and ask for human clarification.
