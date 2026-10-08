"""Execute the actual workflow shell steps without publishing to GitHub."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml


WORKFLOW = yaml.safe_load(Path('.github/workflows/plugin-publish.yml').read_text())
STEPS = {step['name']: step for step in WORKFLOW['jobs']['publish']['steps']}


def shell(name, cwd, env):
    return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', STEPS[name]['run']],
                          cwd=cwd, env={**os.environ, **env}, text=True, capture_output=True)


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


@pytest.fixture
def metadata(tmp_path):
    output = tmp_path / 'outputs'
    result = shell('Get basic info from manifest', Path.cwd(), {'GITHUB_OUTPUT': str(output)})
    assert result.returncode == 0, result.stderr
    values = dict(line.split('=', 1) for line in output.read_text().splitlines())
    return {key.upper(): value for key, value in values.items()}


def test_workflow_shell_syntax():
    for step in STEPS.values():
        if 'run' in step:
            result = subprocess.run(['bash', '-n'], input=step['run'], text=True, capture_output=True)
            assert result.returncode == 0, result.stderr


def test_missing_publish_secret(tmp_path):
    result = shell('Check publishing credentials', tmp_path, {'GH_TOKEN': ''})
    assert result.returncode != 0
    assert 'PLUGIN_ACTION' in result.stdout


def test_package_push_first_run_and_retries(tmp_path, metadata):
    remote = tmp_path / 'remote.git'
    git(tmp_path, 'init', '--bare', str(remote))
    seed = tmp_path / 'seed'
    git(tmp_path, 'init', '-b', 'main', str(seed))
    git(seed, 'config', 'user.name', 'Test')
    git(seed, 'config', 'user.email', 'test@example.com')
    (seed / 'README').write_text('seed')
    git(seed, 'add', 'README')
    git(seed, 'commit', '-m', 'seed')
    git(seed, 'remote', 'add', 'origin', str(remote))
    git(seed, 'push', 'origin', 'main')
    branch = metadata['BRANCH_NAME']
    heads = []
    for index, package in enumerate(['package v1', 'package v1', 'package v2']):
        run_dir = tmp_path / f'run-{index}'
        run_dir.mkdir()
        checkout = run_dir / 'dify-plugins'
        git(run_dir, 'clone', '--branch', 'main', str(remote), str(checkout))
        (run_dir / metadata['PACKAGE_NAME']).write_text(package)
        result = shell('Commit and push package', checkout, metadata)
        assert result.returncode == 0, result.stderr
        heads.append(git(remote, 'rev-parse', f'refs/heads/{branch}'))
        path = f"{metadata['AUTHOR']}/{metadata['PLUGIN_NAME']}/{metadata['PACKAGE_NAME']}"
        assert git(remote, 'show', f'{branch}:{path}') == package
    assert heads[0] == heads[1]  # Identical package: no empty commit.
    assert heads[2] != heads[1]
    assert git(remote, 'rev-parse', f'{heads[2]}^') == heads[1]  # No history rewrite.


@pytest.mark.parametrize('scenario,success,creates', [
    ('new', True, True), ('existing', True, False),
    ('lookup_error', False, False), ('create_error', False, True),
])
def test_pr_creation_and_errors(tmp_path, metadata, scenario, success, creates):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'gh.log'
    mock = bin_dir / 'gh'
    mock.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['GH_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
scenario = os.environ['SCENARIO']
if sys.argv[1] == 'api':
    if scenario == 'lookup_error':
        sys.exit(1)
    if scenario == 'existing':
        print('https://github.com/langgenius/dify-plugins/pull/123')
elif scenario == 'create_error':
    sys.exit(1)
''')
    mock.chmod(0o755)
    result = shell('Create PR via GitHub API', tmp_path, {
        **metadata, 'GH_TOKEN': 'dummy', 'RUNNER_TEMP': str(tmp_path),
        'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'GH_LOG': str(log), 'SCENARIO': scenario,
    })
    assert (result.returncode == 0) is success
    import json
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert f"head={metadata['AUTHOR']}:{metadata['BRANCH_NAME']}" in calls[0]
    assert (len(calls) == 2) is creates
    if creates:
        assert calls[1][calls[1].index('--head') + 1] == f"{metadata['AUTHOR']}:{metadata['BRANCH_NAME']}"
        body_file = Path(calls[1][calls[1].index('--body-file') + 1])
        assert metadata['VERSION'] in body_file.read_text()
