from __future__ import annotations

import pytest

from find_fel_nzbdav.nzbdav import (
    NZBDavClient,
    storage_to_webdav_path,
    wait_for_terminal_job,
)


def test_submit_uses_nzbdav_api_addurl_endpoint():
    calls = []

    class FakeHttp:
        def get_json(self, url, timeout=300):
            calls.append((url, timeout))
            return {"status": True, "nzo_ids": ["abc"]}

    client = NZBDavClient(FakeHttp(), "http://server:3000", "secret")

    assert client.submit("http://hydra/getnzb/1", "job") == "abc"
    assert calls[0][0].startswith("http://server:3000/api?")
    assert "/sabnzbd/api" not in calls[0][0]
    assert "mode=addurl" in calls[0][0]
    assert "apikey=secret" in calls[0][0]
    assert "name=http%3A%2F%2Fhydra%2Fgetnzb%2F1" in calls[0][0]
    assert "nzbname=job" in calls[0][0]
    assert calls[0][1] == 300


def test_submit_bytes_uses_addfile_multipart_upload():
    calls = []

    class FakeHttp:
        def post_multipart_json(self, url, *, field_name, filename, data, timeout=300):
            calls.append((url, field_name, filename, data, timeout))
            return {"status": True, "nzo_ids": ["abc"]}

    client = NZBDavClient(FakeHttp(), "http://server:3000", "secret")

    assert client.submit_bytes(b"<nzb/>", "job", timeout=120) == "abc"
    assert calls == [
        (
            "http://server:3000/api?mode=addfile&nzbname=job&output=json&apikey=secret",
            "nzbfile",
            "job.nzb",
            b"<nzb/>",
            120,
        )
    ]


def test_submit_rejects_failed_response_without_nzo_id():
    class FakeHttp:
        def get_json(self, url, timeout=300):
            return {"status": False}

    client = NZBDavClient(FakeHttp(), "http://server:3000", "secret")

    with pytest.raises(RuntimeError, match="NZBDAV submit failed"):
        client.submit("http://hydra/getnzb/1", "job")


def test_queue_status_returns_matching_slot():
    class FakeHttp:
        def get_json(self, url, timeout=10):
            return {
                "queue": {
                    "slots": [
                        {"nzo_id": "other", "status": "Downloading", "name": "other"},
                        {
                            "nzo_id": "abc",
                            "status": "Paused",
                            "name": "job",
                            "filename": "job.nzb",
                        },
                    ]
                }
            }

    client = NZBDavClient(FakeHttp(), "http://server:3000", "secret")

    slot = client.queue_status("abc")

    assert slot is not None
    assert slot.nzo_id == "abc"
    assert slot.status == "Paused"
    assert slot.name == "job"


def test_history_returns_completed_storage():
    class FakeHttp:
        def get_json(self, url, timeout=10):
            return {
                "history": {
                    "slots": [
                        {
                            "nzo_id": "abc",
                            "status": "Completed",
                            "storage": "/content/uncategorized/job/",
                            "name": "job",
                        }
                    ]
                }
            }

    client = NZBDavClient(FakeHttp(), "http://server:3000", "secret")

    history = client.history("abc")

    assert history is not None
    assert history.status == "Completed"
    assert history.storage == "/content/uncategorized/job/"


def test_wait_for_terminal_job_polls_until_history_terminal_status():
    statuses = ["Downloading", "Downloading"]
    sleeps = []

    class FakeClient:
        def queue_status(self, nzo_id):
            if statuses:
                return type("Job", (), {"status": statuses.pop(0), "storage": None})()
            return None

        def history(self, nzo_id):
            return type(
                "Job",
                (),
                {
                    "status": "Completed",
                    "storage": "/content/uncategorized/job/",
                    "name": "job",
                },
            )()

    result = wait_for_terminal_job(
        FakeClient(),
        "abc",
        poll_interval=2,
        timeout=10,
        sleep=sleeps.append,
    )

    assert result.status == "Completed"
    assert result.storage == "/content/uncategorized/job/"
    assert sleeps == [2, 2]


def test_wait_for_terminal_job_raises_on_failed_status():
    class FakeClient:
        def queue_status(self, nzo_id):
            return None

        def history(self, nzo_id):
            return type("Job", (), {"status": "Failed", "storage": None})()

    with pytest.raises(RuntimeError, match="terminal status Failed"):
        wait_for_terminal_job(FakeClient(), "abc", sleep=lambda _: None)


def test_wait_for_terminal_job_timeout_uses_injected_clock():
    sleeps = []
    clock_values = iter([0, 1, 3])

    class FakeClient:
        def queue_status(self, nzo_id):
            return type("Job", (), {"status": "Downloading", "storage": None})()

        def history(self, nzo_id):
            raise AssertionError("history should not be checked while job is queued")

    with pytest.raises(TimeoutError, match="Timed out waiting for NZBDAV job abc"):
        wait_for_terminal_job(
            FakeClient(),
            "abc",
            poll_interval=1,
            timeout=2,
            sleep=sleeps.append,
            monotonic=lambda: next(clock_values),
        )

    assert sleeps == [1]


def test_storage_to_webdav_path_handles_known_layouts():
    assert storage_to_webdav_path("/content/uncategorized/job/") == (
        "/content/uncategorized/job/"
    )
    assert storage_to_webdav_path(
        "/mnt/nzbdav/completed-symlinks/uncategorized/job"
    ) == "/content/uncategorized/job/"
    assert storage_to_webdav_path(
        "/mnt/data/completed-symlinks/uncategorized/job"
    ) == "/content/uncategorized/job/"


def test_storage_to_webdav_path_falls_back_to_last_two_components():
    assert storage_to_webdav_path("/some/other/layout/category/job") == (
        "/content/category/job/"
    )
