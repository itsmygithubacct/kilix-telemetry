from __future__ import annotations

import concurrent.futures
import json
import os
import select
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import linux_tree
from kilix_telemetry.client import TelemetryClient, ensure_running
from kilix_telemetry.consumers import ConsumerRegistry, MAX_CONSUMERS, process_identity
from kilix_telemetry.ring import TelemetryError, daemon_running, resolve_paths


class ConsumerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / 'linux'
        self.root.mkdir()
        linux_tree(self.root)
        self.paths = resolve_paths(self.base / 'runtime')
        self.children = []
        self.command = [sys.executable, '-m', 'kilix_telemetry', 'serve', '--quiet',
                        '--root', str(self.root), '--interval', '.1', '--idle-timeout', '.2']
        self.environment = mock.patch.dict(os.environ, {
            'KILIX_TELEMETRY_COMMAND': shlex.join(self.command),
            'KILIX_TELEMETRY_DISABLE': '0',
        })
        self.environment.start()

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for child in self.children:
            if child.stdin is not None and not child.stdin.closed:
                child.stdin.close()
        self.environment.stop()
        self.temporary.cleanup()

    def owner(self):
        child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'],
                                 stdin=subprocess.PIPE)
        self.children.append(child)
        return child

    def release(self, child):
        child.stdin.close()
        child.wait(timeout=2)

    def wait_stopped(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not daemon_running(self.paths):
                return
            time.sleep(.03)
        self.fail('automatic sampler remained alive after every owner exited')

    def automatic(self, owner):
        # Capture only test-created direct children, so failures cannot abandon
        # a sampler while TemporaryDirectory removes its runtime endpoints.
        real_spawn = subprocess.Popen
        def spawn(*args, **kwargs):
            child = real_spawn(*args, **kwargs)
            self.children.append(child)
            return child
        with mock.patch('kilix_telemetry.client.subprocess.Popen', side_effect=spawn):
            self.assertTrue(ensure_running(self.paths, owner_pid=owner.pid))

    def test_last_owner_exit_stops_writer(self):
        owner = self.owner()
        self.automatic(owner)
        self.release(owner)
        self.wait_stopped()

    def test_one_owner_exit_preserves_other_owner(self):
        first, second = self.owner(), self.owner()
        self.automatic(first)
        self.assertTrue(ensure_running(self.paths, owner_pid=second.pid))
        writer = self.paths.lock.read_text()
        self.release(first)
        time.sleep(.4)
        self.assertTrue(daemon_running(self.paths))
        self.assertEqual(self.paths.lock.read_text(), writer)
        self.release(second)
        self.wait_stopped()

    def test_concurrent_start_shares_writer_and_retains_both_owners(self):
        owners = [self.owner(), self.owner()]
        real_spawn = subprocess.Popen
        def spawn(*args, **kwargs):
            child = real_spawn(*args, **kwargs)
            self.children.append(child)
            return child
        with mock.patch('kilix_telemetry.client.subprocess.Popen', side_effect=spawn):
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda owner: ensure_running(
                    self.paths, owner_pid=owner.pid), owners))
        self.assertEqual(results, [True, True])
        records = json.loads(ConsumerRegistry(self.paths).file.read_text())
        self.assertEqual(set(records), {str(owner.pid) for owner in owners})
        self.release(owners[0])
        time.sleep(.4)
        self.assertTrue(daemon_running(self.paths))
        self.release(owners[1])
        self.wait_stopped()

    def test_existing_writer_acquires_lazy_snapshot_consumer(self):
        owner = self.owner()
        self.automatic(owner)
        client = TelemetryClient(self.paths)
        try:
            self.assertIsNotNone(client.snapshot(start=True, fallback=False))
            self.release(owner)
            time.sleep(.4)
            self.assertTrue(daemon_running(self.paths))
            records = json.loads(ConsumerRegistry(self.paths).file.read_text())
            self.assertIn(str(os.getpid()), records)
        finally:
            client.close()

    def test_reused_pid_and_changed_namespace_do_not_keep_writer_alive(self):
        registry = ConsumerRegistry(self.paths)
        registry.register(os.getpid())
        actual = process_identity(os.getpid())
        self.assertTrue(registry.active())
        with mock.patch('kilix_telemetry.consumers.process_identity', return_value=actual + ':other'):
            self.assertFalse(registry.active())

    def test_foreign_uid_and_zombie_are_rejected(self):
        with mock.patch('kilix_telemetry.consumers.os.getuid', return_value=os.getuid() + 1):
            self.assertIsNone(process_identity(os.getpid()))
        with mock.patch('kilix_telemetry.consumers.Path.read_text', return_value='1 (x) Z ' + '0 ' * 20):
            self.assertIsNone(process_identity(os.getpid()))

    def test_forked_client_registers_new_process_even_for_cached_sample(self):
        client = TelemetryClient(self.paths, fallback_root=self.root)
        client.snapshot(start=False)
        client._consumer_pid = os.getpid()
        client._cached_until = float('inf')
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(read_fd)
                client.snapshot(start=True)
                records = json.loads(ConsumerRegistry(self.paths).file.read_text())
                os.write(write_fd, b'yes' if str(os.getpid()) in records else b'no')
                os._exit(0)
            except BaseException:
                os._exit(1)
        os.close(write_fd)
        try:
            self.assertTrue(select.select([read_fd], [], [], 2)[0])
            self.assertEqual(os.read(read_fd, 3), b'yes')
        finally:
            os.close(read_fd)
            os.waitpid(pid, 0)
            client.close()

    def test_failed_and_stalled_startup_are_reaped(self):
        owner = self.owner()
        for command in ([sys.executable, '-c', 'raise SystemExit(7)'],
                        [sys.executable, '-c', 'import time; time.sleep(60)']):
            real_spawn = subprocess.Popen
            spawned = []
            def spawn(*args, **kwargs):
                child = real_spawn(*args, **kwargs)
                spawned.append(child)
                self.children.append(child)
                return child
            with mock.patch.dict(os.environ, {'KILIX_TELEMETRY_COMMAND': shlex.join(command)}):
                with mock.patch('kilix_telemetry.client.subprocess.Popen', side_effect=spawn):
                    self.assertFalse(ensure_running(self.paths, timeout=.1, owner_pid=owner.pid))
            self.assertEqual(len(spawned), 1)
            spawned[0].wait(timeout=2)
            self.assertIsNotNone(spawned[0].returncode)

    def test_explicit_serve_remains_persistent_without_consumers(self):
        command = self.command[:-2]
        environment = dict(os.environ, KILIX_TELEMETRY_RUNTIME=str(self.paths.directory))
        process = subprocess.Popen(command, env=environment)
        self.children.append(process)
        time.sleep(.5)
        self.assertIsNone(process.poll())
        self.assertTrue(daemon_running(self.paths))

    def test_registry_refuses_symlink_and_prunes_dead_records(self):
        registry = ConsumerRegistry(self.paths)
        registry.register(os.getpid())
        registry.file.write_text(json.dumps({'999999999': 'old'}))
        registry.register(os.getpid())
        self.assertEqual(set(json.loads(registry.file.read_text())), {str(os.getpid())})
        registry.file.unlink()
        target = self.base / 'target'
        target.write_text('preserve')
        registry.file.symlink_to(target)
        with self.assertRaises(OSError):
            registry.register(os.getpid())
        self.assertEqual(target.read_text(), 'preserve')

    def test_live_registry_population_is_bounded(self):
        registry = ConsumerRegistry(self.paths)
        registry.register(os.getpid())
        with mock.patch.object(registry, '_live', return_value={str(i + 100000): 'x' for i in range(MAX_CONSUMERS)}):
            with self.assertRaises(TelemetryError):
                registry.register(os.getpid())


if __name__ == '__main__':
    unittest.main()
