# Changelog

## 0.0.3

- Expose input `direct_output` / `overridden` strategies with English, Chinese,
  and Japanese labels. Existing settings default to `direct_output`.
- Validate JSON payloads, supported moderation points, and field types.
- Preserve non-string input values without raising type errors.
- Authenticate before JSON parsing, use constant-time key comparison, and reject
  missing configured keys. Return consistent JSON errors.
- Reject empty separators, empty keyword lists, and invalid strategy settings.
- Deduplicate keywords and mask original overlapping spans consistently, including
  overlapping occurrences of the same keyword.
- Correct masking labels to `***` and add regression tests and CI.

## 0.0.2

- Keyword moderation endpoint with configurable output handling and Bearer authentication.
