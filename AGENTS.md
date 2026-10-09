# Engineering standards

These standards apply to existing code and new changes in this repository.

- Read the affected implementation before editing. Keep changes focused; do not overwrite unrelated work.
- Load credentials from environment/configuration; never commit operational secrets. Generate ephemeral test credentials at runtime.
- Validate untrusted input at boundaries. Parameterize SQL, contain filesystem paths, and avoid unsafe deserialization and HTML injection.
- Keep modules cohesive, functions concise, and names domain-specific. Document non-obvious decisions rather than narrating code.
- Handle expected failures explicitly without exposing credentials or internal exception text. Do not conceal programming errors behind success responses.
- Prefer existing dependencies. Justify new dependencies, verify maintenance status, and document their licenses.
- Add meaningful regression tests for core logic and security changes. Run relevant tests and builds, and report any unverified behavior.
- Distinguish live, historical, mock and unknown-provenance data. Never infer production readiness from a successful build alone.
