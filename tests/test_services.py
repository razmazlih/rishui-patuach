"""Lifecycle safety checks using mocks only; no services or datasets are accessed."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'services.py'
spec = importlib.util.spec_from_file_location('project_services_under_test', MODULE_PATH)
services = importlib.util.module_from_spec(spec)
spec.loader.exec_module(services)


class ServiceLifecycle(unittest.TestCase):
    def setUp(self):
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_existing_native_cluster_wins_over_available_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            cluster = data / 'work' / 'postgres'
            cluster.mkdir(parents=True)
            (cluster / 'PG_VERSION').touch()
            with patch.object(services, 'DATA', data), \
                 patch.object(services, 'managed_database', return_value=True), \
                 patch.object(services, 'docker_available', return_value=True) as docker, \
                 patch.object(services, 'database_ready', return_value=True), \
                 patch.object(services, 'run') as run:
                self.assertEqual(services.start_database(), 'native')
                docker.assert_not_called()
                run.assert_called_once_with(['sh', 'scripts/local-postgres.sh', 'start'])

    def test_external_database_is_checked_but_never_started(self):
        with patch.object(services, 'managed_database', return_value=False), \
             patch.object(services, 'database_ready', return_value=True), \
             patch.object(services, 'run') as run, \
             patch.object(services, 'docker_available') as docker:
            self.assertEqual(services.start_database(), 'external')
            run.assert_not_called()
            docker.assert_not_called()

    def test_unreachable_external_database_refuses_local_fallback(self):
        with patch.object(services, 'managed_database', return_value=False), \
             patch.object(services, 'database_ready', return_value=False), \
             patch.object(services, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'external PostgreSQL'):
                services.start_database()
            run.assert_not_called()

    def test_busy_unmanaged_port_refuses_before_database_or_build_mutation(self):
        with patch.object(services, 'state', return_value={}), \
             patch.object(services, 'web_running', return_value=False), \
             patch.object(services, 'port_busy', return_value=True), \
             patch.object(services, 'start_database') as database, \
             patch.object(services, 'run') as run, \
             patch.object(services.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'unmanaged process'):
                services.start()
            database.assert_not_called()
            run.assert_not_called()
            spawn.assert_not_called()

    def test_identity_stays_stable_when_next_changes_process_title(self):
        creation_time = 'Sun Nov  1 12:00:00 2026'
        with patch.object(services.subprocess, 'run', return_value=Mock(
                returncode=0, stdout='  ' + creation_time + '\n')) as ps:
            identity_at_boot = services.process_identity(4567)
            # A later check must use creation time, independently of a changed command title.
            self.assertEqual(identity_at_boot, creation_time)
            self.assertTrue(services.web_running({'pid': 4567, 'identity': identity_at_boot}))
            self.assertEqual(ps.call_count, 2)
            for call in ps.call_args_list:
                self.assertEqual(call.args[0], ['ps', '-p', '4567', '-o', 'lstart='])
                self.assertFalse(any('command' in arg or 'args=' in arg for arg in call.args[0]))

    def test_stop_never_signals_reused_pid_with_mismatched_identity(self):
        saved = {'pid': 4567, 'identity': 'old creation time'}
        state_file = Mock()
        with patch.object(services, 'state', return_value=saved), \
             patch.object(services, 'process_identity', return_value='different creation time'), \
             patch.object(services, 'STATE', state_file), \
             patch.object(services.os, 'getpgid') as getpgid, \
             patch.object(services.os, 'killpg') as signal_group:
            services.stop_web()
            getpgid.assert_not_called()
            signal_group.assert_not_called()
            state_file.unlink.assert_called_once_with(missing_ok=True)

    def test_stop_refuses_changed_process_group(self):
        saved = {'pid': 4567, 'identity': 'same identity'}
        with patch.object(services, 'state', return_value=saved), \
             patch.object(services, 'process_identity', return_value='same identity'), \
             patch.object(services.os, 'getpgid', return_value=9999), \
             patch.object(services.os, 'killpg') as signal_group:
            with self.assertRaisesRegex(RuntimeError, 'process group changed'):
                services.stop_web()
            signal_group.assert_not_called()

    def test_repeated_start_of_healthy_managed_server_is_idempotent(self):
        saved = {'pid': 4567, 'identity': 'same identity', 'url': 'http://127.0.0.1:3000'}
        with patch.object(services, 'state', return_value=saved), \
             patch.object(services, 'process_identity', return_value='same identity'), \
             patch.object(services, 'database_ready', return_value=True), \
             patch.object(services, 'http_ready', return_value=True), \
             patch.object(services, 'start_database') as database, \
             patch.object(services, 'port_busy') as port_busy, \
             patch.object(services, 'run') as run, \
             patch.object(services.subprocess, 'Popen') as spawn:
            services.start()
            services.start()
            database.assert_not_called()
            port_busy.assert_not_called()
            run.assert_not_called()
            spawn.assert_not_called()

    def test_down_stops_both_project_backends_without_removing_storage(self):
        with patch.object(services, 'stop_web') as stop_web, \
             patch.object(services, 'native_status', return_value=True), \
             patch.object(services, 'docker_available', return_value=True), \
             patch.object(services, 'run') as run:
            services.down()
            stop_web.assert_called_once_with()
            self.assertEqual([call.args[0] for call in run.call_args_list], [
                ['sh', 'scripts/local-postgres.sh', 'stop'],
                ['docker', 'compose', 'down'],
            ])
            for call in run.call_args_list:
                self.assertTrue({'-v', '--volumes', 'rm', 'prune', 'initdb', '--remove-orphans'}.isdisjoint(call.args[0]))


if __name__ == '__main__':
    unittest.main()
