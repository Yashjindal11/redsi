# Security Policy

## Reporting a vulnerability in RedSI

Please **do not** open a public issue. Report privately through
[GitHub security advisories](https://github.com/Yashjindal11/redsi/security/advisories/new).
Include the affected version (`redsi --version`), a description, and a minimal
reproduction. You can expect an acknowledgement within a week. Fixes are
released as patch versions and credited in the changelog unless you prefer
otherwise.

Supported versions: the latest minor release.

## RedSI's threat model

RedSI runs user-supplied code and sends adversarial inputs to systems, so its
own safety properties matter:

| Concern | Default behaviour |
|---|---|
| User target code | Runs in-process (it is the user's own code). `--isolate` / `Target.from_import(..., isolate=True)` runs each call in a separate process that is killed on timeout. |
| Hangs | Every target call has a timeout (default 60 s). |
| Shell execution | RedSI never executes shell commands. Built-in evaluators never execute model-generated code. |
| Network | RedSI only contacts the target URL you configure and the model providers you configure. The HTTP target does not follow redirects. Nothing is sent anywhere else; there is no telemetry. |
| Secrets | Keys are read from environment variables by *name*; artifacts store the variable name only. A redactor scrubs common key formats and the values of secret-looking environment variables from events, artifacts and reports. |
| Judge manipulation | Outputs under evaluation are fenced and judges are told to ignore instructions inside them; judge evidence must quote the output or confidence is halved. Treat LLM judges as fallible regardless. |
| Web dashboard | Binds to `127.0.0.1` by default, is read-only, and serves only files from the run store. Do not expose it publicly without authentication in front of it. |

## Responsible use

RedSI is for evaluating systems you own or are explicitly authorised to test.
The security-oriented suites use synthetic canary tokens and harmless marker
strings; they measure whether a system leaks or obeys injected content. They
are not exploit kits, and contributions that turn them into one will not be
accepted.
