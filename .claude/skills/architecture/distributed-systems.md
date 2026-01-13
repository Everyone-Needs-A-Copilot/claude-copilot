---
skill_name: distributed-systems
skill_category: architecture
description: Design distributed systems with anti-patterns for consensus, consistency, and fault tolerance
allowed_tools: [Read, Edit, Glob, Grep]
token_estimate: 2100
version: 1.0
last_updated: 2026-01-13
owner: Claude Copilot
status: active
tags: [distributed, microservices, consensus, consistency, fault-tolerance, scalability, architecture]
related_skills: [api-design]
trigger_files: ["**/services/**", "**/microservices/**", "**/queue/**", "**/kafka/**", "**/redis/**"]
trigger_keywords: [distributed, microservice, consensus, eventual consistency, partition, replication, fault tolerance, saga, cqrs]
---

# Distributed Systems

Design distributed systems with proper handling of consensus, consistency, and fault tolerance.

## Purpose

Distributed systems introduce complexity that single-node systems don't face. This skill helps navigate trade-offs and avoid common pitfalls when designing systems that span multiple nodes, services, or regions.

## Fundamental Concepts

### CAP Theorem

You can only guarantee two of three properties:

| Property | Description | Example |
|----------|-------------|---------|
| **Consistency** | All nodes see same data | Banking systems |
| **Availability** | Every request gets response | Shopping carts |
| **Partition tolerance** | System works despite network splits | Any distributed system |

**Reality:** Network partitions happen. Choose CP (consistency) or AP (availability).

### PACELC Extension

When Partitioned: Choose A or C
Else (normal operation): Choose Latency or Consistency

| System Type | Partition | Normal | Example |
|-------------|-----------|--------|---------|
| CP/EC | Consistency | Consistency | Traditional RDBMS |
| AP/EL | Availability | Latency | Caching systems |
| AP/EC | Availability | Consistency | Cassandra |
| CP/EL | Consistency | Latency | MongoDB |

## Design Patterns

### 1. Saga Pattern

For distributed transactions without 2PC:

```
Order Saga:
1. Create Order (pending) → success
2. Reserve Inventory → success
3. Process Payment → success
4. Confirm Order → complete

Compensation (on failure):
- Payment failed → Release Inventory → Cancel Order
```

**Choreography vs Orchestration:**

| Approach | Pros | Cons | Use When |
|----------|------|------|----------|
| Choreography | Decoupled, scalable | Hard to track, debug | Simple flows, few steps |
| Orchestration | Centralized control, observable | Single point of failure | Complex flows, many steps |

### 2. Event Sourcing

Store state as sequence of events:

```
Traditional: UPDATE users SET balance = 100 WHERE id = 1
Event Sourcing:
  - BalanceSet(userId=1, amount=50, timestamp=T1)
  - BalanceIncremented(userId=1, delta=30, timestamp=T2)
  - BalanceDecremented(userId=1, delta=10, timestamp=T3)
  - Current state = replay events = 70
```

| Pro | Con |
|-----|-----|
| Full audit trail | Storage growth |
| Temporal queries | Complex queries |
| Easy replay/debug | Event schema evolution |

### 3. CQRS (Command Query Responsibility Segregation)

Separate read and write models:

```
Commands → Write Model (normalized) → Events → Read Model (denormalized)

Example:
- Command: CreateOrder(items, customer)
- Write: orders, order_items tables
- Event: OrderCreated
- Read: customer_order_summary (denormalized view)
```

| Use When | Avoid When |
|----------|------------|
| Read/write ratios differ significantly | Simple CRUD |
| Complex read queries | Data consistency critical |
| Different scaling needs | Small data volumes |

## Anti-Patterns

### 1. Distributed Monolith

**Problem:** Microservices with tight coupling, synchronous calls everywhere.

```
❌ Service A → sync call → Service B → sync call → Service C
   (one failure cascades, all latencies compound)
```

**Solution:** Async communication, circuit breakers, independent deployability.

```
✅ Service A → message queue → Service B
✅ Service A → cached data (eventual consistency)
✅ Circuit breaker prevents cascade failures
```

### 2. Two-Phase Commit in Microservices

**Problem:** Using 2PC across service boundaries.

```
❌ Coordinator holds locks across Order, Inventory, Payment services
   - High latency
   - Single point of failure
   - Scaling nightmare
```

**Solution:** Saga pattern with compensation.

```
✅ Order Service: Create order (pending)
✅ Inventory Service: Reserve (or compensate)
✅ Payment Service: Charge (or compensate)
✅ Order Service: Confirm/cancel based on results
```

### 3. Ignoring Network Partitions

**Problem:** Assuming network is reliable.

```
❌ Split-brain: Two leaders elected during partition
❌ Stale reads: Client reads from isolated replica
❌ Lost writes: Write to isolated leader not replicated
```

**Solution:** Design for partition tolerance.

```
✅ Quorum reads/writes (majority required)
✅ Leader election with fencing tokens
✅ Conflict resolution strategies (LWW, vector clocks)
```

### 4. Shared Database Anti-Pattern

**Problem:** Multiple services sharing one database.

```
❌ Service A ─┐
❌ Service B ─┼──→ Shared Database
❌ Service C ─┘
   (schema coupling, deployment coupling, scaling coupling)
```

**Solution:** Database per service with API contracts.

```
✅ Service A → DB-A
✅ Service B → DB-B
✅ Services communicate via APIs/events, not shared tables
```

### 5. Synchronous Cascade

**Problem:** Long chains of synchronous calls.

```
❌ API → Auth → User → Permissions → Audit → Response
   Latency = sum of all service latencies
   Availability = product of all service availabilities
   5 services at 99.9% = 99.5% availability
```

**Solution:** Async where possible, caching, aggregation.

```
✅ Cache frequently accessed data (Auth, Permissions)
✅ Async audit logging (fire-and-forget)
✅ Aggregate responses at edge
```

### 6. Missing Idempotency

**Problem:** Duplicate messages cause duplicate effects.

```
❌ ProcessPayment(orderId, $100) × 2 = $200 charged
❌ CreateUser(email) × 2 = duplicate users
```

**Solution:** Idempotency keys, deduplication.

```
✅ ProcessPayment(idempotencyKey, orderId, $100)
   - Store key → result mapping
   - Return cached result on duplicate
✅ CreateUser with unique constraint on email
```

### 7. Lack of Observability

**Problem:** Can't trace requests across services.

```
❌ Error in Service D, no idea which request caused it
❌ Latency spike, don't know which service slow
❌ Debugging requires looking at 10 different logs
```

**Solution:** Distributed tracing, structured logging, metrics.

```
✅ Correlation ID passed through all services
✅ OpenTelemetry/Jaeger for distributed tracing
✅ Centralized logging with trace context
✅ RED metrics: Rate, Errors, Duration per service
```

## Consistency Patterns

### Strong Consistency

| Pattern | How | Trade-off |
|---------|-----|-----------|
| Synchronous replication | Wait for all replicas | High latency |
| Quorum writes | Wait for majority | Moderate latency |
| Linearizable reads | Read from leader | Single point |

### Eventual Consistency

| Pattern | How | Use When |
|---------|-----|----------|
| Async replication | Fire-and-forget | Analytics, caching |
| Last-write-wins (LWW) | Timestamp ordering | Low conflict data |
| Vector clocks | Version tracking | Conflict detection |
| CRDTs | Automatic merge | Counters, sets |

## Design Checklist

### New Service Design

| Check | Question |
|-------|----------|
| Data ownership | Does service own its data? |
| API contract | Is contract versioned and stable? |
| Failure modes | What happens when dependencies fail? |
| Idempotency | Are operations safe to retry? |
| Observability | Can requests be traced end-to-end? |
| Consistency | What consistency level needed? |
| Scalability | Can service scale independently? |

### Inter-Service Communication

| Check | Sync | Async |
|-------|------|-------|
| Latency sensitive | ✓ | |
| Fire-and-forget | | ✓ |
| Needs response | ✓ | ✓ (request-reply) |
| High volume | | ✓ |
| Ordered processing | | ✓ (partitioned) |
| Decoupling needed | | ✓ |

## Output Format

When designing distributed systems:

```markdown
## Distributed System Design: [System Name]

### Architecture Overview

| Service | Responsibility | Data Store | Communication |
|---------|---------------|------------|---------------|
| Service A | ... | PostgreSQL | REST, Kafka |
| Service B | ... | Redis | gRPC |

### Consistency Model

| Data | Consistency | Rationale |
|------|-------------|-----------|
| User accounts | Strong | Security critical |
| Order history | Eventual | Read-heavy, tolerates lag |

### Failure Handling

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Service B down | ... | Circuit breaker, cached fallback |
| Network partition | ... | Quorum writes, reconciliation |

### Anti-Patterns Avoided
- [List specific anti-patterns checked and avoided]

### Trade-offs Made
- [Key decisions with rationale]
```
