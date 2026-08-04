# Dark-first theme with tri-state preference (dark / light / system)

The UI is being redesigned as a dark-first market intelligence terminal. We decided that **dark is the unconditional default for every first-time visitor, regardless of OS appearance**; `system` is an explicit opt-in choice in the theme switcher, never auto-selected. This was decided over the alternative "default = system" because dark is the product's identity (a calm, professional terminal), not an accessibility accommodation — letting the OS flip the product to light mode undermines the positioning.

## Consequences

- `useTheme` moves from a binary (`dark`/`light`) to a tri-state model: `dark` | `light` | `system`. The existing localStorage value is migrated (old `dark`/`light` values map directly; absence of a stored value means `dark`, NOT `system`).
- In `system` mode the app listens to `prefers-color-scheme` changes; in `dark`/`light` mode it ignores them.
- Theme switching UI becomes a three-way control (segmented or menu) instead of the current Sun/Moon toggle-flip.
- This decision is hard to reverse once users have stored preferences, which is why the default is frozen here.
