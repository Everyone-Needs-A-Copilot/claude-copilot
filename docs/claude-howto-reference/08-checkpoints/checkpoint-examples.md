# Checkpoint Examples

Real-world examples of using checkpoints effectively in Claude Code.

## Example 1: Database Migration

### Scenario
You need to migrate from MySQL to PostgreSQL but want to explore both a direct migration and a gradual dual-write approach.

### Workflow

```
User: /checkpoint save "Before database migration"

User: Let's implement a direct migration from MySQL to PostgreSQL

Claude: I'll implement the direct migration...
[Changes database driver, updates queries, modifies schema]

User: /checkpoint save "Direct migration complete"

User: Run the tests

Claude: Running tests...
❌ 15 tests failing - connection pool issues

User: This approach has issues. Let's try the dual-write pattern instead.

Claude: I'll rewind to the starting point...
/checkpoint rewind "Before database migration"

User: Now implement a dual-write pattern where we write to both databases

Claude: I'll implement dual-write migration...
[Implements dual-write layer, gradual migration strategy]

User: /checkpoint save "Dual-write migration complete"

User: Run the tests

Claude: Running tests...
✅ All tests passing

User: /checkpoint compare "Direct migration complete" "Dual-write migration complete"

Claude: Comparison of the two approaches:

Direct Migration:
- Faster to implement
- All-or-nothing cutover
- Higher risk
- Failed integration tests

Dual-Write Migration:
- More complex implementation
- Gradual, safer migration
- Can rollback easily
- All tests passing
- Recommended approach ✅
```

## Example 2: Performance Optimization

### Scenario
Multiple performance optimization strategies to try.

### Workflow

```
User: /checkpoint save "Baseline performance"

User: Let's optimize the API response time. Current: 450ms

Claude: I'll add database query caching...
[Implements Redis caching]

User: /checkpoint save "Redis caching"
User: Run performance tests

Claude: Results: 280ms average response time (38% improvement)

User: /checkpoint rewind "Baseline performance"
User: Try database query optimization instead

Claude: I'll optimize database queries...
[Adds indexes, optimizes N+1 queries]

User: /checkpoint save "Query optimization"
User: Run performance tests

Claude: Results: 180ms average response time (60% improvement)

User: /checkpoint rewind "Baseline performance"
User: Try response compression and CDN

Claude: I'll add compression and CDN...
[Implements gzip, sets up CDN]

User: /checkpoint save "Compression + CDN"
User: Run performance tests

Claude: Results: 320ms average response time (29% improvement)

User: Let's combine query optimization with caching

Claude: I'll rewind to query optimization and add caching...
/checkpoint rewind "Query optimization"
[Adds Redis caching on top of optimized queries]

User: /checkpoint save "Combined approach"
User: Run performance tests

Claude: Results: 95ms average response time (79% improvement) 🎉

User: Perfect! This is the winner. Let's commit this.
```

## Example 3: UI/UX Iteration

### Scenario
Trying different layouts for a dashboard.

### Workflow

```
User: /checkpoint save "Dashboard - current layout"

User: Let's redesign the dashboard with a sidebar layout

Claude: [Implements sidebar layout]
User: /checkpoint save "Sidebar layout"
User: Show me a screenshot

Claude: [Shows screenshot]

User: The sidebar feels cramped. Let's try a top navigation instead.

Claude: /checkpoint rewind "Dashboard - current layout"
[Implements top navigation]
User: /checkpoint save "Top navigation layout"
User: Show me a screenshot

Claude: [Shows screenshot]

User: Better, but let's try a card-based grid layout

Claude: /checkpoint rewind "Dashboard - current layout"
[Implements card grid]
User: /checkpoint save "Card grid layout"
User: Show me a screenshot

Claude: [Shows screenshot]

User: This is great! But can we combine the top nav with the card grid?

Claude: /checkpoint rewind "Card grid layout"
[Adds top navigation to card grid]
User: /checkpoint save "Top nav + card grid"

User: Perfect! This is the final design.
```

## Example 4: Debugging Session

### Scenario
Hunting down a tricky bug with multiple hypotheses.

### Workflow

```
User: There's a memory leak in the application

Claude: Let me investigate...
[Analyzes code]

User: /checkpoint save "Before debugging"

User: I think it's in the event listeners. Let's fix those.

Claude: [Fixes event listener cleanup]
User: /checkpoint save "Event listener fix"
User: Run memory profiler

Claude: Still leaking memory - event listeners weren't the issue

User: /checkpoint rewind "Before debugging"
User: Maybe it's the database connections?

Claude: [Implements connection pooling fixes]
User: /checkpoint save "Connection pooling fix"
User: Run memory profiler

Claude: Still leaking - not the connections either

User: /checkpoint rewind "Before debugging"
User: Let's check for circular references

Claude: [Finds and fixes circular references in cache]
User: /checkpoint save "Circular reference fix"
User: Run memory profiler

Claude: ✅ Memory leak fixed! The circular references in the caching layer were the culprit.

User: Excellent! Let's commit this fix.
```

## Example 5: API Design Evolution

### Scenario
Designing a REST API with multiple iterations.

### Workflow

```
User: /checkpoint save "Before API design"

User: Create a REST API for our blog platform

Claude: [Creates basic CRUD API]
User: /checkpoint save "Basic CRUD API"

User: This is too simple. Let's add pagination and filtering

Claude: [Adds pagination and filtering]
User: /checkpoint save "API with pagination"

User: We need better resource relationships

Claude: [Implements HATEOAS links]
User: /checkpoint save "API with HATEOAS"

User: Actually, let's try GraphQL instead of REST

Claude: /checkpoint rewind "Before API design"
[Implements GraphQL API]
User: /checkpoint save "GraphQL API"

User: /checkpoint compare "API with HATEOAS" "GraphQL API"

Claude: Comparison:

REST with HATEOAS:
+ Simple, well-understood
+ Easy to cache
+ Works with existing tools
- Multiple round trips
- Over-fetching data

GraphQL:
+ Single endpoint
+ Client specifies data needs
+ No over-fetching
- More complex setup
- Harder to cache
- Steeper learning curve

User: For our use case, REST is better. Let's go with that.

Claude: /checkpoint rewind "API with HATEOAS"
```

## Example 6: Configuration Management

### Scenario
Testing different configuration approaches.

### Workflow

```
User: /checkpoint save "Original config"

User: Move configuration to environment variables

Claude: [Implements env var configuration]
User: /checkpoint save "Env var config"
User: Test in development

Claude: Works locally but deployment issues in production

User: /checkpoint rewind "Original config"
User: Try a config file approach with validation

Claude: [Implements YAML config with JSON schema validation]
User: /checkpoint save "Config file with validation"
User: Test in development

Claude: ✅ Works well, good validation errors

User: Can we also support env vars for sensitive values?

Claude: [Adds env var override for secrets]
User: /checkpoint save "Hybrid config approach"
User: Test deployment

Claude: ✅ All environments working correctly

User: Perfect! This is production-ready.
```

## Example 7: Test Strategy

### Scenario
Implementing comprehensive testing.

### Workflow

```
User: /checkpoint save "Before adding tests"

User: Add unit tests for the auth module

Claude: [Adds Jest unit tests]
User: /checkpoint save "Unit tests only"
User: Run tests

Claude: 45 tests passing, 78% coverage

User: Add integration tests too

Claude: [Adds integration tests]
User: /checkpoint save "Unit + Integration tests"
User: Run tests

Claude: 89 tests passing, 92% coverage, but tests are slow (3 minutes)

User: The tests are too slow. Let's optimize.

Claude: [Optimizes test setup, adds parallel execution]
User: /checkpoint save "Optimized tests"
User: Run tests

Claude: 89 tests passing, 92% coverage, 35 seconds ✅

User: Great! Now add E2E tests for critical paths

Claude: [Adds Playwright E2E tests]
User: /checkpoint save "Full test suite"
User: Run all tests

Claude: 112 tests passing, 94% coverage, 2 minutes

User: Perfect balance of coverage and speed!
```

## Key Takeaways

1. **Checkpoint before major changes**: Always create a checkpoint before significant modifications
2. **Name checkpoints descriptively**: Use clear names that explain what was accomplished
3. **Compare approaches**: Use checkpoint diff to evaluate different solutions
4. **Don't fear experimentation**: Checkpoints make it safe to try radical changes
5. **Clean up regularly**: Delete old checkpoints to keep things organized
6. **Combine with git**: Use checkpoints for exploration, git for finalized work
