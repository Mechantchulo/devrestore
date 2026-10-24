# Architecture

The Typer CLI and Textual shell call the same scanner and profile services. Pydantic models define the scan result and versioned YAML manifest. `ProfileStore` owns local persistence. The restore engine maps stable tool IDs to a small static package allowlist, then builds actions before execution. The GitHub adapter uses `gh api` to read and create individual profile files in a selected private repository.

```text
CLI / TUI
  ├── scanner → ScanResult
  ├── ProfileStore ↔ Manifest YAML
  ├── restore planner → allowlisted APT/DNF actions → executor
  └── GitHubSync → gh CLI → private profiles/*.yaml
```

The scanner probes known executable names and versions and separately discovers installed Android, JDK, .NET, and Flutter SDKs. It does not scan every installed package. SDK installations are stored as portable metadata without source paths. The source provider is represented separately from the target restore provider, but provider inference is not yet implemented. Unknown providers stay unknown in the saved profile.

Manifests have `schema_version: 1`; future incompatible changes will need an explicit migration step. The optional `sdks` field is backward compatible with existing version 1 profiles. The current loader rejects unknown top-level keys and unsupported schema versions. GitHub sync compares validated manifests and leaves differing files untouched. The restore planner reports SDKs as unsupported rather than guessing installation steps.

The TUI offers a home menu, scan results with a named profile save action, local profile listing, system status, and command guidance for restore and YAML transfer. Its GitHub section suspends the TUI to run the guided `connect` command or profile sync in the terminal, then resumes. The Set Up This Computer menu action runs the guided CLI `setup` flow in the terminal so GitHub sign-in, profile selection, plan review, and installation confirmation are available without typing a command. The CLI exposes the complete implemented operation set; `connect` saves a private repository selection locally. Full in-TUI restoration progress remains future work.

