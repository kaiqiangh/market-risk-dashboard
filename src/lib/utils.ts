import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Shared class-name utility used by the UI primitives. */

/** shadcn/ui class name merger. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
