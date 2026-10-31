# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub security advisories:
<https://github.com/WPTK/wxbrief/security/advisories/new>. Do not open a public issue for a vulnerability.

Include what you found, how to reproduce it, and the version or commit.

## Scope

wxbrief is a local command-line and terminal tool. It reads public weather data from aviationweather.gov (once the
fetch feature is built) and report text you give it. It has no accounts, handles no secrets and runs no server.

Relevant reports include a crash or hang from crafted report text, unsafe handling of downloaded data, and problems in
the project's build or release workflows.

## Supported versions

There is no release yet. Fixes go to `main` until the first release; after that, only the latest release is supported.
