#!/usr/bin/env python3
"""Exercise the workflow's actual shell steps without signing credentials."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / '.github/workflows/pwragent-release.yml').read_text()
VERSION = '1.0.0-pwragent.test'
FILES = {'grok', 'LICENSE', 'THIRD-PARTY-NOTICES', 'SOURCE_REV', 'PWRAGENT-BUILD.txt'}


def script(name):
    section = WORKFLOW.split(f'      - name: {name}\n', 1)[1]
    section = section.split('\n      - name:', 1)[0].split('\n  windows-prepare:', 1)[0]
    return textwrap.dedent(section.split('        run: |\n', 1)[1])


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GROK_VERSION=VERSION, RUNNER_TEMP=str(self.root),
                        GITHUB_OUTPUT=str(self.root / 'output'), GITHUB_ENV=str(self.root / 'env'),
                        GITHUB_SERVER_URL='https://github.com', GITHUB_REPOSITORY='pwrdrvr/grok-build',
                        GITHUB_SHA='test-source-commit')
        for platform in ('aarch64', 'x86_64'):
            payload = self.root / f'raw/raw-macos-{platform}'
            payload.mkdir(parents=True)
            for name in FILES:
                (payload / name).write_text(f'fixture {name}\n')
            (payload / 'PWRAGENT-BUILD.txt').write_text(f'platform=macos-{platform}\n')
            (payload / 'grok').chmod(0o755)

    def run_step(self, name, success=True):
        result = subprocess.run(['bash', '-c', script(name)], cwd=self.root, env=self.env,
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def stage_fixtures(self):
        for platform, destination in [('aarch64', 'stage-aarch64'), ('x86_64', 'stage')]:
            shutil.copytree(self.root / f'raw/raw-macos-{platform}', self.root / destination)

    def test_archive_digest_and_package_layout(self):
        self.stage_fixtures()
        self.run_step('Archive macOS signing input')
        archive = self.root / 'macos-release-signing-input.tgz'
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual((self.root / 'output').read_text().strip(), f'sha256={digest}')
        with tarfile.open(archive) as tar:
            self.assertEqual({n.removeprefix('./') for n in tar.getnames()},
                             {'stage', 'stage-aarch64'} | {f'{d}/{f}' for d in ('stage', 'stage-aarch64') for f in FILES})
        self.env['EXPECTED_SHA256'] = digest
        inputs = self.root / '.release-input'
        inputs.mkdir()
        for item in (archive, self.root / 'macos-release-signing-input.tgz.sha256'):
            shutil.move(item, inputs / item.name)
        self.run_step('Verify macOS signing input')
        sidecar = inputs / (archive.name + '.sha256')
        recorded = sidecar.read_text()
        sidecar.write_text('0' * 64 + '  ' + archive.name + '\n')
        self.run_step('Verify macOS signing input', success=False)
        sidecar.write_text(recorded)
        shutil.rmtree(self.root / 'stage')
        shutil.rmtree(self.root / 'stage-aarch64')
        subprocess.run(['tar', '-xzf', str(inputs / archive.name)], cwd=self.root, check=True)
        self.run_step('Package signed macOS distribution')
        for platform, directory in [('universal', 'stage'), ('aarch64', 'stage-aarch64')]:
            with tarfile.open(self.root / f'pwragent-grok-{VERSION}-macos-{platform}.tar.gz') as tar:
                members = {m.name.removeprefix('./'): m for m in tar.getmembers() if m.isfile()}
                self.assertEqual(set(members), FILES)
                self.assertTrue(members['grok'].mode & 0o111)
                for name, member in members.items():
                    self.assertEqual(tar.extractfile(member).read(), (self.root / directory / name).read_bytes())
        # A modified archive fails even when its accompanying digest is replaced.
        with (inputs / archive.name).open('ab') as handle:
            handle.write(b'tampered')
        changed = hashlib.sha256((inputs / archive.name).read_bytes()).hexdigest()
        (inputs / (archive.name + '.sha256')).write_text(f'{changed}  {archive.name}\n')
        self.run_step('Verify macOS signing input', success=False)

    def test_exact_release_asset_set(self):
        dist = self.root / 'dist'
        dist.mkdir()
        names = [f'pwragent-grok-{VERSION}-{p}.{ext}' for p, ext in (
            ('macos-universal', 'tar.gz'), ('macos-aarch64', 'tar.gz'),
            ('linux-aarch64', 'tar.gz'), ('linux-x86_64', 'tar.gz'), ('windows-x86_64', 'zip'))]
        for name in names:
            (dist / name).write_text(name)
        # macOS system Bash lacks mapfile and BSD find lacks -printf. Use a
        # portable equivalent for discovery; execute all actual contract checks.
        original = script('Generate checksums')
        discovery = next(line for line in original.splitlines() if 'mapfile -t assets' in line)
        portable = original.replace(discovery, "assets=(); while IFS= read -r name; do assets+=(\"$name\"); done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS | sed 's|^./||' | sort)")
        if sys.platform == 'darwin':
            portable = portable.replace('sha256sum ', 'shasum -a 256 ')
        else:
            portable = original
        def assemble():
            return subprocess.run(['bash', '-c', portable], cwd=self.root, env=self.env,
                                  capture_output=True, text=True)
        self.assertEqual(assemble().returncode, 0)
        self.assertEqual(len((dist / 'SHA256SUMS').read_text().splitlines()), 5)
        for name in names:
            self.assertIn(hashlib.sha256(name.encode()).hexdigest() + '  ' + name,
                          (dist / 'SHA256SUMS').read_text())
        arm = dist / names[1]
        arm.unlink()
        self.assertNotEqual(assemble().returncode, 0)
        (dist / 'unexpected.tar.gz').write_text('unexpected')
        self.assertNotEqual(assemble().returncode, 0)

    @unittest.skipUnless(shutil.which('lipo') and shutil.which('clang'), 'requires Apple build tools')
    def test_native_architectures_and_provenance(self):
        source = self.root / 'fixture.c'
        source.write_text('int main(void) { return 0; }\n')
        for platform, arch in [('aarch64', 'arm64'), ('x86_64', 'x86_64')]:
            subprocess.run(['clang', '-arch', arch, str(source), '-o',
                            str(self.root / f'raw/raw-macos-{platform}/grok')], check=True)
        self.run_step('Merge universal binary')
        for directory, expected in [('stage', {'arm64', 'x86_64'}), ('stage-aarch64', {'arm64'})]:
            archs = subprocess.check_output(['lipo', '-archs', str(self.root / directory / 'grok')], text=True)
            self.assertEqual(set(archs.split()), expected)
        self.assertIn('platform=macos-universal', (self.root / 'stage/PWRAGENT-BUILD.txt').read_text())
        self.assertIn('platform=macos-aarch64', (self.root / 'stage-aarch64/PWRAGENT-BUILD.txt').read_text())
        # Swapping the raw arm64 input for a fat binary must be rejected.
        shutil.copyfile(self.root / 'stage/grok', self.root / 'raw/raw-macos-aarch64/grok')
        self.run_step('Merge universal binary', success=False)


if __name__ == '__main__':
    unittest.main()
