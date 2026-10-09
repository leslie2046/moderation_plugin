# Development and Release Guide

This guide covers development, testing, packaging, and publishing for the Moderation plugin. For Dify setup, endpoint settings, matching behavior, and request errors, see [README.md](README.md). For release changes, see [CHANGELOG.md](CHANGELOG.md).

## Project structure

| Path | Purpose |
| --- | --- |
| `manifest.yaml` | Plugin identity, version, permissions, Python runtime, and endpoint group. |
| `main.py` | Dify SDK entry point. |
| `group/moderation.yaml` | Settings, including independent input and output strategies. |
| `endpoints/moderation.yaml` | POST endpoint declaration at `/`. |
| `endpoints/moderation.py` | Authentication, validation, matching, and masking. |
| `requirements.txt` | Runtime dependencies. |
| `requirements-dev.txt` | Runtime dependencies and pytest. |
| `tests/` | Moderation, SDK declaration, and publishing regression tests. |
| `.difyignore` | Files excluded from packages. |
| `.github/workflows/tests.yml` | Tests on pushes and pull requests. |
| `.github/workflows/plugin-publish.yml` | Package submission on published releases. |

## Development environment

Use **Python 3.12**, matching the manifest and CI. Run commands from the repository root. Keep runtime dependencies in `requirements.txt` and test dependencies in `requirements-dev.txt`.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Linux or macOS:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

If an existing virtual environment references a Python installation that has moved or been removed, create a fresh environment at another path, such as `.venv-test`, and use its Python executable below.

## Regression tests

For moderation behavior and SDK declaration checks on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_moderation.py -q
```

Run the complete suite in Linux or a suitably configured Bash environment:

```bash
.venv/bin/python -m pytest -q
```

Publishing tests execute the workflow shell steps with Bash, Git, local repositories, and a mocked GitHub CLI. They do not publish externally. Windows environments without compatible Bash and Unix utilities should use GitHub Actions for the complete suite.

The **Tests** workflow runs automatically on pushes and pull requests, using Ubuntu and Python 3.12. Check results in Actions or the PR checks. To repeat a run, open it and select **Re-run all jobs** with an account that has the required repository access. The workflow currently has no manual `workflow_dispatch` trigger.

Tests cover blocking and masking, non-string inputs, overlapping keywords, custom separators, authentication, invalid requests and settings, SDK declarations, and publishing retries and failures. They do not verify live Dify installation or actual GitHub publishing permissions.

## Remote debugging

Copy `.env.example` to `.env` and fill in the debugging values supplied by your Dify instance:

```env
INSTALL_METHOD=remote
REMOTE_INSTALL_URL=debug.dify.ai:5003
REMOTE_INSTALL_KEY=your-debugging-key
```

Use the host and key shown by your instance's plugin debugging interface. The debugging key connects the SDK to Dify; it is separate from the moderation endpoint's `api_key`. Keep `.env` and keys out of version control.

Start the plugin on Windows:

```powershell
.\.venv\Scripts\python.exe -m main
```

On Linux or macOS:

```bash
.venv/bin/python -m main
```

In Dify, configure the debugging plugin's endpoint, register its URL and moderation API key as an API extension, and enable content moderation in a test application. See the setup screenshots in [README.md](README.md).

## Integration checks

Configure these test settings:

| Setting | Value |
| --- | --- |
| `api_key` | A test key of your choice. |
| `keywords` | `敏感,bad,abc,bcde` |
| `separator` | `,` |
| `input_preset_response` | `输入被拦截` |
| `output_preset_response` | `输出被拦截` |

Use the endpoint URL provided by Dify, rather than constructing it from the declaration's `/` path. Send POST requests with `Content-Type: application/json` and `Authorization: Bearer <your-test-key>`.

Check connectivity:

```json
{"point":"ping"}
```

Expected response: `{"result":"pong"}`.

Check input moderation:

```json
{
  "point": "app.moderation.input",
  "params": {
    "query": "包含敏感内容",
    "inputs": {
      "name": "bad",
      "count": 3,
      "enabled": true,
      "file": {"name": "bad.txt"}
    }
  }
}
```

- With input strategy `direct_output`, expect `flagged: true`, `action: direct_output`, and `preset_response: 输入被拦截`.
- With input strategy `overridden`, expect `flagged: true`, `action: overridden`, `query: 包含***内容`, and `inputs.name: ***`. The number, boolean, and nested file object must remain unchanged.

Check output moderation and overlapping keywords:

```json
{"point":"app.moderation.output","params":{"text":"xabcdef"}}
```

- With output strategy `direct_output`, expect the output preset response.
- With output strategy `overridden`, expect `text: x***f`: overlapping matches `abc` and `bcde` are masked together.

Also verify normal text returns `flagged: false`, missing credentials return 401, an incorrect key returns 403, and malformed JSON or an unsupported `point` returns 400. See [README.md](README.md) for the complete matching and error contract.

Finally, exercise both strategies in the Dify test application. Inspect run details to confirm input masking changes the text passed to the application and output masking changes the returned text. Direct endpoint tests give deterministic results without depending on model output.

## Packaging

Use your installed Dify plugin CLI. Its executable name may be `dify`, `dify-plugin`, or a platform-specific filename. The publishing workflow currently downloads `dify-plugin-linux-amd64` from daemon release `0.0.6`.

For version 0.0.3, the Windows command used in this repository is:

```powershell
dify.exe plugin package . -o moderation-0.0.3.difypkg
```

With an executable named `dify-plugin`:

```bash
dify-plugin plugin package . -o moderation-0.0.3.difypkg
```

For later versions, update the output filename to match `manifest.yaml`. Check `.difyignore` for local files that should be excluded, then install the package in a test Dify instance. Keep generated packages out of source commits unless intentionally adding a distribution artifact.

## Publishing

The existing workflow runs when a GitHub release is **published**. Publishing starts an external package submission process, so complete tests and package installation checks first.

### Prerequisites

- A fork of `langgenius/dify-plugins` at `<manifest author>/dify-plugins`, with a `main` branch. This plugin uses `leslie2046/dify-plugins`.
- An Actions secret named `PLUGIN_ACTION` in the source repository. Its token must be able to push to the fork and create the intended upstream PR. Local workflow tests do not validate these permissions.
- Consistent versions in the manifest, README, and changelog. Choose a matching release tag and target the tested source commit.
- A complete [PRIVACY.md](PRIVACY.md) and the declared endpoint files and assets.

### What the workflow does

For `moderation` version `0.0.3`, the workflow:

1. Checks that `PLUGIN_ACTION` is present, downloads the CLI, and reads the author, name, and version from the manifest.
2. Builds `moderation-0.0.3.difypkg`.
3. Checks out the fork's `main` branch and creates or reuses `bump-moderation-plugin-0.0.3`.
4. Copies the package to `leslie2046/moderation/moderation-0.0.3.difypkg`, commits it if changed, and pushes the branch without force-pushing.
5. Checks for an existing open upstream PR. If none exists, creates a PR **to `langgenius/dify-plugins`, targeting `main`**, from `leslie2046:bump-moderation-plugin-0.0.3`.

The fork stores the package branch; the PR targets the upstream repository. Successful submission does not guarantee Marketplace acceptance.

### Results and retries

After publishing, inspect **Plugin Publish Workflow** in Actions and the resulting upstream PR. Missing secrets, Git authentication errors, API lookup failures, and PR creation failures should fail the run visibly.

After correcting the cause, re-run the workflow. It reuses an existing remote branch, skips unchanged package commits, and skips PR creation only when an existing open PR is confirmed. Runs for the same release tag are serialized.

The workflow does not currently validate the release tag against the manifest version, verify the fork relationship or all token permissions in advance, or generate release notes from the changelog. Check these manually; planned improvements are listed in [README.md](README.md).
