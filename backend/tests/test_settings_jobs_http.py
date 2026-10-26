"""Settings job contracts observed over HTTP, with only the OS process boundary faked.

No installer, downloader or external account is invoked. These contracts are
consumed by the settings UI: cursors, one active job, refresh and cancellation.
"""
from __future__ import annotations

import threading
import time

import pytest


class FakeJobProcess:
    """A subprocess that emits one line, then waits for cancellation."""

    def __init__(self, *args, **kwargs):
        self.finished = threading.Event()
        self.returncode = None
        self.stdout = self.output()

    def output(self):
        yield 'review job started\n'
        self.finished.wait(5)

    def poll(self):
        return self.returncode

    def wait(self):
        self.finished.wait(5)
        return self.returncode if self.returncode is not None else 1

    def terminate(self):
        self.returncode = -15
        self.finished.set()


def wait_for_status(client, url, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200
        body = response.json()
        if predicate(body):
            return body
        time.sleep(0.01)
    pytest.fail('The HTTP job state did not reach the expected condition')


@pytest.mark.parametrize(
    'start, payload, status, cancel',
    [
        ('/api/settings/document-parsing/install', {'engine': 'docling'},
         '/api/settings/document-parsing/job/status', '/api/settings/document-parsing/job/cancel'),
        ('/api/settings/document-parsing/models/download', {'engine': 'docling'},
         '/api/settings/document-parsing/job/status', '/api/settings/document-parsing/job/cancel'),
        ('/api/settings/mineru/models/download', {'model_type': 'pipeline', 'source': 'huggingface'},
         '/api/settings/mineru/models/download/status', '/api/settings/mineru/models/download/cancel'),
    ],
)
def test_job_refresh_cursor_and_cancellation(client, monkeypatch, start, payload, status, cancel):
    import shutil
    import subprocess

    # Resolve a pretend CLI and replace process creation at the OS boundary.
    monkeypatch.setattr(shutil, 'which', lambda *args, **kwargs: 'fake-review-downloader')
    monkeypatch.setattr(subprocess, 'Popen', FakeJobProcess)
    started = client.post(start, json=payload)
    assert started.status_code == 200
    assert started.json()['ok'] is True
    try:
        first = wait_for_status(client, status, lambda body: bool(body['lines']))
        assert first['state'] == 'running'
        assert first['lines'] == ['review job started']
        # A newly mounted observer can re-read the current process from zero.
        refreshed = client.get(status, params={'cursor': 0}).json()
        assert refreshed['state'] == 'running'
        assert refreshed['lines'] == first['lines']
        incremental = client.get(status, params={'cursor': first['next_cursor']}).json()
        assert incremental['lines'] == []
        assert incremental['next_cursor'] == first['next_cursor']
        blocked = client.post(start, json=payload)
        assert blocked.status_code == 200
        assert blocked.json()['ok'] is False
    finally:
        stopped = client.post(cancel)
        assert stopped.status_code == 200
        assert stopped.json()['ok'] is True
        done = wait_for_status(client, status, lambda body: body['state'] != 'running')
        assert done['state'] == 'cancelled'
    assert client.post(cancel).json()['ok'] is False


def test_unsupported_install_and_download_are_refused_without_a_process(client, monkeypatch):
    import subprocess

    def forbidden_process(*args, **kwargs):
        pytest.fail('Unsupported job must not create a subprocess')

    monkeypatch.setattr(subprocess, 'Popen', forbidden_process)
    assert client.post('/api/settings/document-parsing/install', json={'engine': 'text_only'}).json()['ok'] is False
    assert client.post('/api/settings/document-parsing/models/download', json={'engine': 'tika'}).json()['ok'] is False
