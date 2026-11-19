import assert from "node:assert/strict";
import { test } from "node:test";
import match from "picomatch";

test("lint globs match nested TypeScript files", () => {
  const matches = match("**/*.{ts,tsx}");
  assert.equal(matches("app/settings/page.tsx"), true);
  assert.equal(matches("app/settings/style.css"), false);
});

test("the installed matcher rejects repeated extglobs before compilation", () => {
  for (const pattern of ["+(foo)", "*(bar)"]) {
    assert.throws(() => match(pattern), /Repeated extglobs are disabled/);
  }
});
