"""Tests for the agent-driven side of the bridge.

An agent runs `hskr browser <action>` in a terminal, where there is no pipe into
Chrome. These cover the queue that carries the instruction across that gap and
back.
"""

from __future__ import annotations

import io
import json
import os
import struct
import threading
import time

import pytest

from humble_steam_key_redeemer.bridge import BROWSER_ACTIONS, BridgeError, run_command, run_host
from humble_steam_key_redeemer.bridge import _queue as queue
from humble_steam_key_redeemer.settings import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.delenv("HSKR_STATE_DIR", raising=False)
    settings = Settings(state_dir=tmp_path / "state")
    settings.ensure_state_dir()
    return settings


def _framed(message: dict) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def _messages(raw: bytes) -> list[dict]:
    """Decode every framed message in a stream."""
    stream = io.BytesIO(raw)
    out = []
    while header := stream.read(4):
        (length,) = struct.unpack("<I", header)
        out.append(json.loads(stream.read(length)))
    return out


class _BlockingStream:
    """A stream that blocks on read until closed, the way Chrome's pipe does."""

    def __init__(self) -> None:
        self._closed = threading.Event()

    def read(self, _size: int) -> bytes:
        self._closed.wait()
        return b""

    def close(self) -> None:
        self._closed.set()


class TestQueue:
    def test_a_request_is_claimed_once(self, settings):
        """Two hosts must not both serve the same instruction."""
        request_id = queue.submit(settings.state_dir, {"action": "sync"})

        first = queue.claim(settings.state_dir)
        second = queue.claim(settings.state_dir)

        assert first == {"requestId": request_id, "action": "sync"}
        assert second is None

    def test_concurrent_hosts_do_not_both_serve_a_request(self, settings):
        """A duplicated redeem replays a whole plan against Steam's budget."""
        for _ in range(20):
            queue.submit(settings.state_dir, {"action": "redeem"})

        served: list[dict] = []
        barrier = threading.Barrier(4)

        def host() -> None:
            barrier.wait()
            while (request := queue.claim(settings.state_dir)) is not None:
                served.append(request)

        threads = [threading.Thread(target=host) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        ids = [request["requestId"] for request in served]
        assert len(ids) == len(set(ids)) == 20

    def test_a_corrupt_request_is_discarded_not_served(self, settings):
        """Half a JSON file is not an instruction to act on."""
        directory = queue.queue_directory(settings.state_dir)
        (directory / "broken.request").write_text('{"action": "rede')

        assert queue.claim(settings.state_dir) is None
        # And it does not linger to be retried forever.
        assert list(directory.glob("*.request")) == []

    def test_a_good_request_after_a_corrupt_one_is_still_served(self, settings):
        directory = queue.queue_directory(settings.state_dir)
        (directory / "broken.request").write_text("not json at all")
        request_id = queue.submit(settings.state_dir, {"action": "status"})

        claimed = queue.claim(settings.state_dir)

        assert claimed is not None
        assert claimed["requestId"] == request_id

    def test_a_reply_reaches_the_waiting_caller(self, settings):
        request_id = queue.submit(settings.state_dir, {"action": "status"})
        queue.respond(settings.state_dir, request_id, {"ok": True, "reply": {"humble": True}})

        assert queue.collect(settings.state_dir, request_id, timeout=1)["ok"] is True

    def test_waiting_gives_up_and_withdraws_the_request(self, settings):
        """A request nobody served must not be run after the caller left."""
        request_id = queue.submit(settings.state_dir, {"action": "redeem"})

        assert queue.collect(settings.state_dir, request_id, timeout=0.3) is None
        assert queue.claim(settings.state_dir) is None

    def test_queued_files_are_private(self, settings):
        """Requests name keys and titles, so they are not world-readable."""
        queue.submit(settings.state_dir, {"action": "sync"})

        directory = queue.queue_directory(settings.state_dir)
        assert directory.stat().st_mode & 0o077 == 0
        for path in directory.iterdir():
            assert path.stat().st_mode & 0o077 == 0

    def test_a_stale_request_is_swept_rather_than_served(self, settings, monkeypatch):
        """Chrome was closed when this was queued; running it later is wrong."""
        queue.submit(settings.state_dir, {"action": "redeem"})
        path = next(queue.queue_directory(settings.state_dir).glob("*.request"))

        old = time.time() - 3600
        os.utime(path, (old, old))

        assert queue.claim(settings.state_dir) is None
        assert not path.exists()


class TestRunCommand:
    def test_an_unknown_action_is_rejected(self, settings):
        with pytest.raises(BridgeError, match="Unknown browser action"):
            run_command("delete-everything", settings)

    def test_a_silent_browser_is_reported(self, settings):
        with pytest.raises(BridgeError, match="did not respond"):
            run_command("status", settings, timeout=0.3)

    def test_the_reply_comes_back(self, settings):
        """The whole path: submit, someone serves it, the reply arrives."""

        def serve() -> None:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                request = queue.claim(settings.state_dir)
                if request:
                    queue.respond(
                        settings.state_dir,
                        request["requestId"],
                        {"ok": True, "reply": {"humble": True, "steam": True}},
                    )
                    return
                time.sleep(0.05)

        server = threading.Thread(target=serve)
        server.start()
        try:
            reply = run_command("status", settings, timeout=5)
        finally:
            server.join()

        assert reply["reply"] == {"humble": True, "steam": True}

    def test_every_advertised_action_is_accepted(self, settings):
        """What the CLI help lists must be what the host will queue."""
        for action in BROWSER_ACTIONS:
            with pytest.raises(BridgeError, match="did not respond"):
                run_command(action, settings, timeout=0.2)


class TestHostServesBothDirections:
    def test_a_queued_instruction_is_pushed_to_the_extension(self, settings):
        """The agent's instruction has to travel out over Chrome's own pipe."""
        request_id = queue.submit(settings.state_dir, {"action": "sync", "reveal": False})

        # A stream that stays open lets the host live long enough for its pump
        # to notice the queued instruction, the way Chrome's pipe would.
        stdin = _BlockingStream()
        stdout = io.BytesIO()
        host = threading.Thread(target=run_host, args=(stdin, stdout, settings), daemon=True)
        host.start()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not stdout.getvalue():
                time.sleep(queue.POLL_SECONDS)
        finally:
            stdin.close()
            host.join(timeout=5)

        assert _messages(stdout.getvalue()) == [{"requestId": request_id, "action": "sync", "reveal": False}]

    def test_a_disconnect_mid_run_tells_the_waiting_agent(self, settings):
        """Otherwise the terminal sits out a timeout that can be 15 minutes."""
        request_id = queue.submit(settings.state_dir, {"action": "redeem"})

        stdin = _BlockingStream()
        stdout = io.BytesIO()
        host = threading.Thread(target=run_host, args=(stdin, stdout, settings), daemon=True)
        host.start()
        try:
            # Wait until the instruction has actually gone out to the browser.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not stdout.getvalue():
                time.sleep(queue.POLL_SECONDS)
        finally:
            stdin.close()  # the browser goes away mid-run
            host.join(timeout=5)

        reply = queue.collect(settings.state_dir, request_id, timeout=2)
        assert reply is not None
        assert reply["ok"] is False
        assert "disconnected" in reply["error"]

    def test_a_question_is_answered_under_the_id_it_asked_with(self, settings):
        """Both directions share one pipe, so replies must be correlatable."""
        stdin = io.BytesIO(_framed({"command": "status", "replyTo": "abc"}))
        stdout = io.BytesIO()

        run_host(stdin, stdout, settings)

        [message] = _messages(stdout.getvalue())
        assert message["replyTo"] == "abc"
        assert message["reply"]["ok"] is True

    def test_an_answer_to_an_instruction_goes_back_to_the_agent(self, settings):
        """A reply carrying a requestId belongs to a waiting terminal, not here."""
        request_id = queue.submit(settings.state_dir, {"action": "status"})
        stdin = io.BytesIO(_framed({"requestId": request_id, "ok": True, "reply": {"humble": True}}))
        stdout = io.BytesIO()

        run_host(stdin, stdout, settings)

        assert queue.collect(settings.state_dir, request_id, timeout=1)["reply"] == {"humble": True}
        # It must not also be answered down the pipe as though it were a question.
        assert _messages(stdout.getvalue()) == []
