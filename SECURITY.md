# Security Policy

## Supported Versions

VoiceBridge is currently developed from `master`. Security fixes are applied to the latest public source state only unless a release branch is explicitly created.

## Reporting a Vulnerability

Please do not open public issues for security-sensitive reports.

Preferred options:

1. Use GitHub private vulnerability reporting if it is enabled for this repository.
2. If private reporting is not available, contact the maintainer privately before publishing details.

Include:

- affected version or commit;
- operating system and runtime context;
- steps to reproduce;
- impact and whether local files, generated audio, models or credentials are exposed.

## Scope

Relevant reports include:

- accidental exposure of local files or generated datasets;
- unsafe handling of user-selected paths;
- command execution or subprocess injection risks;
- packaging mistakes that include private data;
- dependency or model download behavior that can compromise local data.

Not in scope:

- reports requiring already-compromised local admin access;
- issues in third-party online services such as Microsoft Edge TTS;
- license or model policy questions without a security impact.
