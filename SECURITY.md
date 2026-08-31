# Security policy

## Supported version

Only the latest commit on `main` is reviewed for security fixes. No version is
approved for real participant data or production clinical use.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, participant
information, private endpoints or deployment logs. Use GitHub's private
security advisory feature for this repository, or contact the repository owner
through another verified private channel.

Include the affected commit, component, minimal synthetic reproduction, impact
and suggested mitigation. Do not test against systems or data you do not own or
have explicit authorization to assess.

## Data handling

Security reproductions must use generated synthetic data. Remove secrets and
environment-specific identifiers before sharing logs. The maintainers will not
request API keys, passwords, participant reports or production database copies.

## Disclosure

The maintainer will acknowledge a valid report, reproduce it with synthetic
data and coordinate a reasonable disclosure timeline. This policy is not a bug
bounty or authorization to perform intrusive testing.
