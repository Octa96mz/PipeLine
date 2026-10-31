# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: open this repository's **Security** tab and choose
**Report a vulnerability**. Please do not open a public issue.

Include what you found, how to reproduce it and its possible impact. Never include real API keys, or
your own configuration or database.

This is a personal project, so responses are best effort, and there is no guaranteed response time.

## Supported versions

Only the latest commit on `main` is supported.

## Scope

In scope:

- Exposure of an API key, for example in logs, stored errors or files with wide permissions
- A way to make the bar, the panel or `pipeline json` contact a data provider
- Escaping the collector service's sandbox
- `install.sh` or `uninstall.sh` overwriting or deleting something without asking, or following a
  symbolic link outside what they manage
- Malicious provider responses that cause anything beyond rejected or wrong prices

Out of scope:

- Delayed or incorrect prices from a data provider
- Other processes running as your own user reading your files
- Issues in Omarchy, Quickshell, systemd or a data provider, which should go to their own projects

The [threat model](README.md#threat-model) explains these limits.
