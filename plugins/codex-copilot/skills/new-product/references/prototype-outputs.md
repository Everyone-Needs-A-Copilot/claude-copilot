# Prototype Outputs (Phase 6)

After the Design Complete Checkpoint passes, the user chooses one output. Phase 6 is creation mode: build the output from everything documented in Phases 1 to 5. Only one format is created; if the user needs more than one, complete the primary first.

## Choosing

| Output | What you get | Guide in the project | Prerequisites |
|--------|-------------|----------------------|---------------|
| Figma Design | Complete UI layouts in Figma | `docs/06-prototype/00-figma-design.md` | A Figma account and a Figma MCP server configured in the assistant |
| Design Spec | Token, component and layout documentation | `docs/06-prototype/10-design-spec.md` | Nothing extra |
| Storybook | Interactive component library | `docs/06-prototype/20-storybook.md` | Node.js and npm |
| Next.js Prototype | Working clickable application | `docs/06-prototype/30-nextjs-prototype.md` | Node.js and npm |

If the user is not sure, ask: "Who needs to experience this, and what will they do with it?" Then recommend:

| If they want... | Suggest |
|-----------------|---------|
| To hand off to a developer | Design Spec |
| To test interactions quickly | Next.js Prototype |
| To build a component library | Storybook |
| To present to stakeholders visually | Figma Design |

## Prerequisite checks (inline, only for the chosen output)

- Storybook or Next.js: run `node --version` and `npm --version`. If either is missing, tell the user what to install and offer the other outputs meanwhile.
- Figma: confirm a Figma MCP server is available to the assistant (for example by asking it to identify the signed-in Figma user). If it is not, offer Design Spec, Storybook or Next.js instead.

## Hand-off

The Storybook and Next.js outputs are prototypes built from the design package. If the user wants to continue into real product development, hand off to the framework's build workflow (the protocol workflow's Flow A: UI implementation, then technical architecture, then implementation) with `docs/` as the source specifications, rather than extending the prototype by hand.
