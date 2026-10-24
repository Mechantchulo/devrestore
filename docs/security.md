# Security boundaries

- Manifests are parsed with PyYAML `safe_load` and validated with Pydantic. They contain metadata, not commands.
- Tool scanning runs only predefined executable names and version arguments. Each version process has a three-second timeout.
- SDK scanning reads only known local metadata files and uses `dotnet --list-sdks` with a five-second timeout. It does not run SDK managers, accept licenses, or install SDK components.
- Only package names in the restore registry can reach the installer. Package commands use argument arrays, and installations require `--apply`.
- Exact version requests that cannot be satisfied by an already installed tool are blocked rather than silently substituted.
- Profile names are restricted to safe filename characters. Local profile files are written atomically with mode `0600`; import rejects symlinks. Existing profile files and export destinations are not replaced by default.
- GitHub sync uses the user's existing `gh` authentication. It requires a private repository and refuses profile conflicts. It handles profile YAML only; configuration files and secrets are not uploaded.

Current limitations: scanner version output can be incomplete; executable presence does not prove package ownership; the package installer has no rollback after partial success; and full configuration content backup is not implemented. Review every restore plan before applying it.

