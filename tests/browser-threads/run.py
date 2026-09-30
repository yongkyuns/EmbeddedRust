#!/usr/bin/env python3
"""Actual Chrome/Safari via their WebDrivers; no Selenium or browser substitution."""
from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

EXPECTED = dict(main_entries=1, rounds=4, joined_workers=8, messages=2048,
                checksum=4 * 3 * 256 * 257 // 2, backpressure_checks=8,
                tls_isolation=True, timeout=True, disconnect=True, tls_drops=8, cpu_peer_steps=64)


def verify_success(q):
    assert q['isolated'] and q['sharedMemory'], 'shared memory unavailable'
    assert q['done'] and q['exitCode'] == 0 and not q['aborted'], 'unclean exit'
    assert q['entries'] == 1, 'main did not execute exactly once'
    assert q['reports'] == [EXPECTED], 'missing, duplicate or incorrect Rust report'
    assert q['cpuTicks'] >= 2, 'UI heartbeat stalled during Rust CPU work'
    assert not q['errors'], f"browser/runtime errors: {q['errors']}"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.isolated = not self.path.startswith('/unisolated/')
        if not self.isolated:
            self.path = self.path.removeprefix('/unisolated')
        super().do_GET()

    def end_headers(self):
        if getattr(self, 'isolated', True):
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, *_args):
        pass


def self_test():
    q = dict(isolated=True, sharedMemory=True, done=True, exitCode=0,
             aborted=False, entries=1, reports=[EXPECTED], cpuTicks=10, errors=[])
    verify_success(q)
    changes = [dict(reports=[]), dict(reports=[EXPECTED, EXPECTED]),
               dict(entries=0), dict(exitCode=7), dict(done=False),
               dict(cpuTicks=0), dict(isolated=False), dict(aborted=True),
               dict(errors=['trap']), dict(reports=[dict(EXPECTED, checksum=0)])]
    changes.extend([dict(reports=[dict(EXPECTED, tls_drops=7)]),
                    dict(reports=[dict(EXPECTED, cpu_peer_steps=63)])])
    for change in changes:
        invalid = copy.deepcopy(q)
        invalid.update(change)
        try:
            verify_success(invalid)
        except AssertionError:
            continue
        raise AssertionError(f'negative control accepted: {change}')
    print(f'PASS: {len(changes)} oracle negative controls')

    # Session startup is an infrastructure budget, not the Rust execution timeout.
    from unittest.mock import MagicMock, patch
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"value": {"ready": true}}'
    with patch('urllib.request.urlopen', return_value=response) as transport:
        for method, path, expected in [('POST', '/session', 90),
                                       ('POST', '/session/test/execute/sync', 15),
                                       ('DELETE', '/session/test', 15)]:
            request('http://127.0.0.1', method, path)
            assert transport.call_args.kwargs['timeout'] == expected
    with patch('urllib.request.urlopen', side_effect=TimeoutError('injected')) as transport:
        try:
            request('http://127.0.0.1', 'POST', '/session')
        except TimeoutError as error:
            assert 'POST /session' in str(error) and '90s' in str(error)
        else:
            raise AssertionError('session timeout was swallowed')
        assert transport.call_count == 1, 'session creation must not be retried'
    print('PASS: 4 transport timeout controls')


def request(base, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    # A cold Safari session can exceed the ordinary command timeout. Only session
    # creation gets this bounded startup allowance; test/teardown budgets stay put.
    timeout = 90 if (method, path) == ('POST', '/session') else 15
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            value = json.load(response).get('value')
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from error
    except TimeoutError as error:
        raise TimeoutError(f'WebDriver {method} {path} exceeded {timeout}s') from error
    if isinstance(value, dict) and 'error' in value:
        raise RuntimeError(value)
    return value


def driver_configuration(browser):
    if browser == 'safari':
        path = shutil.which('safaridriver')
        assert path, 'actual Apple safaridriver is required'
        return path, {'browserName': 'safari'}
    binary = os.environ.get('BROWSER_BINARY')
    if not binary:
        candidates = ['/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
                      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                      shutil.which('google-chrome'), shutil.which('google-chrome-stable')]
        binary = next((p for p in candidates if p and Path(p).is_file()), None)
    assert binary, 'actual Google Chrome is required (no Chromium substitution)'
    directory = os.environ.get('CHROMEWEBDRIVER')
    path = str(Path(directory) / 'chromedriver') if directory else shutil.which('chromedriver')
    assert path and Path(path).is_file(), 'ChromeDriver is required'
    return path, {'browserName': 'chrome', 'goog:chromeOptions': {
        'binary': binary, 'args': ['--headless=new', '--no-sandbox', '--disable-dev-shm-usage']}}


def run(args):
    site = args.site.resolve()
    manifest = json.loads((site / 'manifest.json').read_text())
    assert manifest['source_sha'] == args.expected_source, 'artifact/source mismatch'
    for name, digest in manifest['files'].items():
        assert Path(name).name == name, 'invalid artifact path'
        assert hashlib.sha256((site / name).read_bytes()).hexdigest() == digest, name
    path, capabilities = driver_configuration(args.browser)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
              functools.partial(Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    origin = f'http://127.0.0.1:{server.server_port}'
    result = dict(browser=args.browser, manifest=manifest, cases=[], success=False,
                  stage='driver-startup')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    session = None
    with args.output.with_suffix('.driver.log').open('w') as log:
        command = [path, '--port', str(port)] if args.browser == 'safari' else [path, f'--port={port}']
        driver = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    request(base, 'GET', '/status')
                    break
                except (OSError, RuntimeError):
                    if driver.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('WebDriver failed to start')
                    time.sleep(0.1)
            result['stage'] = 'session-creation'
            session_start = time.monotonic()
            created = request(base, 'POST', '/session',
                              {'capabilities': {'alwaysMatch': capabilities}})
            result['session_startup_seconds'] = time.monotonic() - session_start
            session = f"/session/{created['sessionId']}"
            result['capabilities'] = created['capabilities']
            result['stage'] = 'browser-cases'
            def execute(script):
                return request(base, 'POST', session + '/execute/sync',
                               {'script': script, 'args': []})
            for mode in ['pass', 'pass', 'pass', 'fail', 'unisolated']:
                page = '/unisolated/index.html' if mode == 'unisolated' else '/index.html'
                request(base, 'POST', session + '/url', {'url': origin + page + '?case=' + mode})
                deadline = time.monotonic() + 60
                q = None
                while time.monotonic() < deadline:
                    q = execute('return window.qualification || null;')
                    if q and q.get('done'):
                        break
                    time.sleep(0.05)
                result['cases'].append({'mode': mode, 'observed': q})
                assert q and q['done'], f'{mode}: timed out or missing result'
                if mode == 'pass':
                    verify_success(q)
                elif mode == 'fail':
                    assert q['exitCode'] == 7 and q['reports'] == [] and q['entries'] == 1
                    assert any('RUSTCAM_INJECTED_FAILURE' in e for e in q['errors'])
                else:
                    assert not q['isolated'] and q['phase'] == 'unsupported'
                    assert q['entries'] == 0 and q['reports'] == []
                print(f'PASS: {args.browser} {mode}', flush=True)
            result['user_agent'] = execute('return navigator.userAgent;')
            result['success'] = True
            result['stage'] = 'complete'
        except Exception as error:
            result['error'] = str(error)
            raise
        finally:
            args.output.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2), flush=True)
            if session:
                try:
                    request(base, 'DELETE', session)
                except Exception:
                    pass
            driver.terminate()
            try:
                driver.wait(timeout=5)
            except subprocess.TimeoutExpired:
                driver.kill()
                driver.wait()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--browser', choices=['chrome', 'safari'])
    parser.add_argument('--site', type=Path)
    parser.add_argument('--expected-source')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not all((args.browser, args.site, args.expected_source, args.output)):
            parser.error('--browser, --site, --expected-source and --output are required')
        run(args)
