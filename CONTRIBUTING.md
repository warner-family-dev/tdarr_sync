# Contributing

## Commit messages
Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` new functionality
- `fix:` bug fix
- `docs:` docs only
- `refactor:` code change that neither fixes a bug nor adds a feature
- `perf:`, `test:`, `chore:`, etc.

Examples:
- `feat(sync): archive originals only after restore`
- `fix(sqlite): handle locked DB with retry`

## Branching
- `development` is where active work lands.
- `main` is protected and receives fast-forward merges from `development` for releases.

## Changelog
Maintain `CHANGELOG.md` using [Keep a Changelog]. Update **Unreleased** and cut a version section when tagging.
