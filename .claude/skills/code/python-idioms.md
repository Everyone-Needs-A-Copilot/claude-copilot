---
skill_name: python-idioms
skill_category: code
description: Pythonic code patterns, anti-patterns, and quality rules
allowed_tools: [Read, Edit, Write, Grep]
token_estimate: 1800
version: 1.0
last_updated: 2026-01-13
owner: Claude Copilot
status: active
tags: [python, idioms, patterns, quality, django, flask]
related_skills: [testing-patterns, api-design]
trigger_files: ["*.py", "**/*.py", "requirements.txt", "pyproject.toml", "setup.py"]
trigger_keywords: [python, django, flask, pytest, pythonic, pep8, type-hints]
---

# Python Idioms

Pythonic patterns, anti-patterns, and quality rules for clean Python code.

## Core Principles

| Principle | Description |
|-----------|-------------|
| **Explicit > Implicit** | Clear, readable code over clever tricks |
| **EAFP** | Easier to Ask Forgiveness than Permission |
| **Duck Typing** | Focus on behavior, not types |
| **Flat > Nested** | Avoid deep nesting |

## Patterns vs Anti-Patterns

### List/Dict Comprehensions

```python
# GOOD: List comprehension
squares = [x**2 for x in range(10) if x % 2 == 0]

# BAD: Manual loop for simple transforms
squares = []
for x in range(10):
    if x % 2 == 0:
        squares.append(x**2)
```

### Context Managers

```python
# GOOD: Context manager for resources
with open('file.txt') as f:
    content = f.read()

# BAD: Manual resource management
f = open('file.txt')
try:
    content = f.read()
finally:
    f.close()
```

### Unpacking

```python
# GOOD: Tuple unpacking
first, *rest, last = items
x, y = point

# BAD: Index access
first = items[0]
last = items[-1]
x = point[0]
y = point[1]
```

### Iteration

```python
# GOOD: Direct iteration
for item in items:
    process(item)

# GOOD: Enumerate when index needed
for i, item in enumerate(items):
    print(f"{i}: {item}")

# BAD: Range-based iteration
for i in range(len(items)):
    process(items[i])
```

### Dictionary Operations

```python
# GOOD: dict.get() with default
value = data.get('key', default_value)

# GOOD: setdefault for initialization
cache.setdefault(key, []).append(item)

# BAD: Check and access
if 'key' in data:
    value = data['key']
else:
    value = default_value
```

### String Formatting

```python
# GOOD: f-strings (Python 3.6+)
message = f"Hello, {name}! You have {count} items."

# OK: .format() for dynamic templates
template = "Hello, {name}!"
message = template.format(name=name)

# BAD: % formatting or concatenation
message = "Hello, " + name + "!"
message = "Hello, %s!" % name
```

### Boolean Checks

```python
# GOOD: Truthiness
if items:  # Not empty
if not items:  # Empty
if value is None:  # Explicit None check

# BAD: Explicit comparisons
if len(items) > 0:
if items != []:
if value == None:
```

## Anti-Patterns to Avoid

### Mutable Default Arguments

```python
# BAD: Mutable default
def add_item(item, items=[]):  # Items shared across calls!
    items.append(item)
    return items

# GOOD: None sentinel
def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
```

### Bare Except

```python
# BAD: Catches everything including KeyboardInterrupt
try:
    risky_operation()
except:
    pass

# GOOD: Specific exceptions
try:
    risky_operation()
except (ValueError, TypeError) as e:
    logger.error(f"Operation failed: {e}")
```

### Global State

```python
# BAD: Global mutable state
_cache = {}
def get_data(key):
    global _cache
    if key not in _cache:
        _cache[key] = fetch(key)
    return _cache[key]

# GOOD: Class with instance state
class DataCache:
    def __init__(self):
        self._cache = {}

    def get(self, key):
        if key not in self._cache:
            self._cache[key] = self._fetch(key)
        return self._cache[key]
```

### Using `type()` for Type Checks

```python
# BAD: type() comparison
if type(obj) == list:
    process_list(obj)

# GOOD: isinstance for type checks
if isinstance(obj, (list, tuple)):
    process_sequence(obj)
```

## Type Hints

```python
# Function signatures
def process_items(items: list[str], max_count: int = 10) -> dict[str, int]:
    ...

# Optional types
from typing import Optional
def find_user(user_id: int) -> Optional[User]:
    ...

# Generic types
from typing import TypeVar, Generic
T = TypeVar('T')
class Container(Generic[T]):
    def __init__(self, value: T) -> None:
        self.value = value
```

## Error Handling

```python
# Custom exceptions with context
class ValidationError(Exception):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"{field}: {message}")

# Chained exceptions
try:
    parse_config(data)
except json.JSONDecodeError as e:
    raise ConfigError("Invalid config format") from e
```

## Quality Checklist

| Check | Rule |
|-------|------|
| No mutable defaults | Use `None` sentinel pattern |
| Specific exceptions | Never bare `except:` |
| Type hints | All public functions annotated |
| No global state | Use classes or dependency injection |
| Comprehensions | For simple transforms (<3 conditions) |
| Context managers | For all resource handling |
| f-strings | For string interpolation |
| isinstance() | Never `type() ==` |

## Django-Specific

```python
# GOOD: QuerySet optimization
users = User.objects.select_related('profile').filter(active=True)

# GOOD: Bulk operations
User.objects.bulk_create([User(name=n) for n in names])
User.objects.filter(old=True).update(status='archived')

# BAD: N+1 queries
for user in User.objects.all():
    print(user.profile.name)  # Query per user!
```

## Flask-Specific

```python
# GOOD: Application factory
def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(config or 'config.default')
    register_blueprints(app)
    return app

# GOOD: Request context
from flask import g, current_app
def get_db():
    if 'db' not in g:
        g.db = connect_db(current_app.config['DATABASE'])
    return g.db
```
