---
skill_name: react-patterns
skill_category: code
description: React component patterns, hooks, anti-patterns, and quality rules
allowed_tools: [Read, Edit, Write, Grep]
token_estimate: 1800
version: 1.0
last_updated: 2026-01-13
owner: Claude Copilot
status: active
tags: [react, hooks, components, jsx, frontend, ui, patterns]
related_skills: [javascript-patterns, testing-patterns]
trigger_files: ["*.tsx", "*.jsx", "**/components/**", "**/hooks/**"]
trigger_keywords: [react, hooks, useState, useEffect, component, jsx, props, context]
---

# React Patterns

Modern React patterns, hooks best practices, anti-patterns, and quality rules.

## Core Principles

| Principle | Description |
|-----------|-------------|
| **Composition** | Small, focused components over inheritance |
| **Unidirectional** | Data flows down, events flow up |
| **Declarative** | Describe what, not how |
| **Hooks** | Functional components with hooks over class components |

## Component Patterns

### Functional Components

```tsx
// GOOD: Typed functional component
interface ButtonProps {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
  disabled?: boolean;
}

export function Button({
  label,
  onClick,
  variant = 'primary',
  disabled = false,
}: ButtonProps) {
  return (
    <button
      className={`btn btn-${variant}`}
      onClick={onClick}
      disabled={disabled}
    >
      {label}
    </button>
  );
}

// BAD: Class component (outdated)
class Button extends React.Component { }
```

### Composition Over Props Drilling

```tsx
// GOOD: Compound components
function Card({ children }: { children: React.ReactNode }) {
  return <div className="card">{children}</div>;
}

Card.Header = function CardHeader({ children }: { children: React.ReactNode }) {
  return <div className="card-header">{children}</div>;
};

Card.Body = function CardBody({ children }: { children: React.ReactNode }) {
  return <div className="card-body">{children}</div>;
};

// Usage
<Card>
  <Card.Header>Title</Card.Header>
  <Card.Body>Content</Card.Body>
</Card>
```

### Render Props / Children as Function

```tsx
// GOOD: Flexible render pattern
interface DataFetcherProps<T> {
  url: string;
  children: (data: T | null, loading: boolean, error: Error | null) => React.ReactNode;
}

function DataFetcher<T>({ url, children }: DataFetcherProps<T>) {
  const { data, loading, error } = useFetch<T>(url);
  return <>{children(data, loading, error)}</>;
}

// Usage
<DataFetcher<User[]> url="/api/users">
  {(users, loading, error) => {
    if (loading) return <Spinner />;
    if (error) return <ErrorMessage error={error} />;
    return <UserList users={users!} />;
  }}
</DataFetcher>
```

## Hooks Best Practices

### useState

```tsx
// GOOD: Typed state
const [user, setUser] = useState<User | null>(null);
const [items, setItems] = useState<Item[]>([]);

// GOOD: Functional updates for derived state
setCount(prev => prev + 1);
setItems(prev => [...prev, newItem]);

// BAD: Object mutation
setUser({ ...user, name: 'New' });  // Works but...
user.name = 'New';  // NEVER mutate directly!
setUser(user);
```

### useEffect

```tsx
// GOOD: Proper dependency array
useEffect(() => {
  const controller = new AbortController();

  async function fetchData() {
    try {
      const response = await fetch(url, { signal: controller.signal });
      setData(await response.json());
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(error as Error);
      }
    }
  }

  fetchData();
  return () => controller.abort();
}, [url]);  // Re-run when url changes

// BAD: Missing dependencies
useEffect(() => {
  fetchData(userId);  // userId not in deps - stale closure!
}, []);

// BAD: Object/array in deps (always new reference)
useEffect(() => {
  doSomething(options);
}, [options]);  // Infinite loop if options = {} inline
```

### useMemo / useCallback

```tsx
// GOOD: Expensive computation
const sortedItems = useMemo(
  () => items.sort((a, b) => a.name.localeCompare(b.name)),
  [items]
);

// GOOD: Stable callback for child props
const handleClick = useCallback(
  (id: string) => {
    onSelect(id);
  },
  [onSelect]
);

// BAD: Premature optimization
const double = useMemo(() => value * 2, [value]);  // Too simple

// BAD: No deps for callback
const handleClick = useCallback(() => {
  onSelect(selectedId);  // selectedId is stale!
}, []);
```

### Custom Hooks

```tsx
// GOOD: Extract reusable logic
function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : initialValue;
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);

  return [value, setValue] as const;
}

// Usage
const [theme, setTheme] = useLocalStorage('theme', 'light');
```

## Anti-Patterns to Avoid

### Index as Key

```tsx
// BAD: Index key causes render issues
{items.map((item, index) => (
  <Item key={index} data={item} />  // Re-renders all on reorder!
))}

// GOOD: Stable unique key
{items.map(item => (
  <Item key={item.id} data={item} />
))}
```

### Props in State

```tsx
// BAD: Copying props to state
function UserProfile({ user }: { user: User }) {
  const [userData, setUserData] = useState(user);  // Stale!
  // ...
}

// GOOD: Derive from props or use effect to sync
function UserProfile({ user }: { user: User }) {
  const displayName = user.name.toUpperCase();  // Derive directly
  // ...
}
```

### useEffect for Transforms

```tsx
// BAD: Effect for derived data
const [items, setItems] = useState([]);
const [filtered, setFiltered] = useState([]);

useEffect(() => {
  setFiltered(items.filter(i => i.active));
}, [items]);

// GOOD: Compute directly or useMemo
const filtered = useMemo(
  () => items.filter(i => i.active),
  [items]
);
```

### Excessive Re-renders

```tsx
// BAD: New object/function on every render
<Child
  config={{ theme: 'dark' }}  // New object every render!
  onClick={() => handleClick(id)}  // New function every render!
/>

// GOOD: Stable references
const config = useMemo(() => ({ theme: 'dark' }), []);
const handleChildClick = useCallback(() => handleClick(id), [id]);

<Child config={config} onClick={handleChildClick} />
```

## State Management

### Context for Global State

```tsx
// GOOD: Typed context with provider
interface AuthContextType {
  user: User | null;
  login: (credentials: Credentials) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
```

### Reducer for Complex State

```tsx
type Action =
  | { type: 'SET_LOADING' }
  | { type: 'SET_DATA'; payload: Data }
  | { type: 'SET_ERROR'; payload: Error };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SET_LOADING':
      return { ...state, loading: true, error: null };
    case 'SET_DATA':
      return { ...state, loading: false, data: action.payload };
    case 'SET_ERROR':
      return { ...state, loading: false, error: action.payload };
  }
}
```

## Quality Checklist

| Check | Rule |
|-------|------|
| Unique keys | Never use index as key for dynamic lists |
| Hook deps | All dependencies listed, no lint suppressions |
| No props in state | Derive from props directly |
| Stable callbacks | useCallback for event handlers passed to children |
| Error boundaries | Wrap feature sections |
| Typed props | Interface for all component props |
| Controlled inputs | value + onChange, not defaultValue |
| Cleanup effects | Return cleanup function for subscriptions |
| Memoize expensive | useMemo for costly computations only |
| Custom hooks | Extract reusable stateful logic |
