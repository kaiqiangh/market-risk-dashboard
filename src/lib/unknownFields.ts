import { z } from "zod";

/**
 * Find fields present in the data but absent from the schema (#101).
 *
 * The generated contracts are `.passthrough()`, not `.strict()`: the pipeline forbids
 * extra fields on the way out, and the frontend tolerates them on the way in so that
 * shipping a new field cannot blank a page. Tolerating them silently is the failure mode
 * that trade-off invites — a producer adds `change_5d`, nobody notices for two months,
 * and the field quietly means nothing. So we tolerate and report.
 *
 * Zod strips nothing in passthrough mode, so the extra keys cannot be recovered by
 * diffing input against output; the shape has to be walked directly.
 */

/** Distinct field paths reported per call. Enough to see the shape of a drift, not a wall. */
const MAX_FIELDS = 20;

/** Upper bound on visited nodes, so a 5000-row dataset cannot stall the fetch. */
const NODE_BUDGET = 20_000;

/** Nesting depth guard for self-referential schemas. */
const MAX_DEPTH = 12;

interface Walk {
  found: Set<string>;
  budget: number;
}

/**
 * Peel the wrappers that do not change an object's key set, so `.nullable().default({})`
 * still resolves to the ZodObject underneath.
 */
function unwrap(schema: z.ZodTypeAny): z.ZodTypeAny {
  let current = schema;
  for (let i = 0; i < 20; i += 1) {
    if (
      current instanceof z.ZodOptional ||
      current instanceof z.ZodNullable ||
      current instanceof z.ZodDefault
    ) {
      current = current._def.innerType as z.ZodTypeAny;
    } else if (current instanceof z.ZodEffects) {
      current = current._def.schema as z.ZodTypeAny;
    } else if (current instanceof z.ZodLazy) {
      current = current._def.getter() as z.ZodTypeAny;
    } else {
      return current;
    }
  }
  return current;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function join(path: string, key: string): string {
  return path ? `${path}.${key}` : key;
}

function walk(schema: z.ZodTypeAny, value: unknown, path: string, state: Walk, depth: number): void {
  if (state.budget <= 0 || state.found.size >= MAX_FIELDS || depth > MAX_DEPTH) return;
  if (value === null || value === undefined) return;
  state.budget -= 1;

  const node = unwrap(schema);

  if (node instanceof z.ZodObject) {
    if (!isPlainObject(value)) return;
    const shape = node.shape as Record<string, z.ZodTypeAny>;
    for (const key of Object.keys(value)) {
      const child = shape[key];
      if (!child) {
        state.found.add(join(path, key));
        if (state.found.size >= MAX_FIELDS) return;
        continue;
      }
      walk(child, value[key], join(path, key), state, depth + 1);
      if (state.found.size >= MAX_FIELDS || state.budget <= 0) return;
    }
    return;
  }

  if (node instanceof z.ZodArray) {
    if (!Array.isArray(value)) return;
    const element = node._def.type as z.ZodTypeAny;
    for (const item of value) {
      // Collapse the index: 400 assets carrying the same stray field is one drift, not 400.
      walk(element, item, `${path}[]`, state, depth + 1);
      if (state.found.size >= MAX_FIELDS || state.budget <= 0) return;
    }
    return;
  }

  if (node instanceof z.ZodRecord) {
    // A record accepts any key by definition; only its values can carry unknown fields.
    if (!isPlainObject(value)) return;
    const valueType = node._def.valueType as z.ZodTypeAny;
    for (const [key, child] of Object.entries(value)) {
      walk(valueType, child, join(path, key), state, depth + 1);
      if (state.found.size >= MAX_FIELDS || state.budget <= 0) return;
    }
    return;
  }

  if (node instanceof z.ZodUnion) {
    // A value that satisfies one branch cleanly has nothing unknown about it; only report
    // when every branch disagrees, and then report the least-surprised branch.
    let best: Set<string> | null = null;
    for (const option of node._def.options as z.ZodTypeAny[]) {
      const branch: Walk = { found: new Set<string>(), budget: state.budget };
      walk(option, value, path, branch, depth + 1);
      if (branch.found.size === 0) return;
      if (best === null || branch.found.size < best.size) best = branch.found;
    }
    if (best) {
      for (const field of best) {
        state.found.add(field);
        if (state.found.size >= MAX_FIELDS) return;
      }
    }
  }
}

/** Field paths present in `value` but not declared by `schema`, deduplicated and sorted. */
export function collectUnknownFields(schema: z.ZodTypeAny, value: unknown): string[] {
  const state: Walk = { found: new Set<string>(), budget: NODE_BUDGET };
  walk(schema, value, "", state, 0);
  return [...state.found].sort();
}
