# Memory Status

Display the current state of Memory Copilot, making the invisible visible.

## Step 1: Show Recent Memories

Run `cc memory search "recent context decisions lessons"` to retrieve recent memories.

Display the last 5 memories:

```
## Recent Memories

| Type | Content | When |
|------|---------|------|
| [decision/lesson/context] | [brief summary - first 80 chars] | [relative time] |
| [type] | [summary] | [time] |
...
```

If no memories found, display:
```
## Recent Memories

No memories stored yet.
```

## Step 2: Show Statistics (Optional)

If the memory system supports retrieving counts, display:

```
## Statistics

Total memories in workspace: [count]
- Decisions: [count]
- Lessons: [count]
- Context: [count]

Database: ~/.claude/memory/[workspace-id].db
```

If counts unavailable, skip this section.

## Implementation Notes

- Use relative timestamps where possible ("recently", "earlier today")
- Truncate long content summaries to keep output readable
- Handle missing fields gracefully (show "Not set" or omit section)
- Don't fail if memory system is unavailable - show error state instead
- Format output for readability with proper markdown tables and lists

## Error Handling

If memory system is unavailable:

```
## Memory Status

Unable to connect to Memory Copilot.

Ensure the `cc` CLI is installed and the memory workspace is configured:
- Run `cc memory --help` for usage
- Check that the workspace ID is set in your project
```
