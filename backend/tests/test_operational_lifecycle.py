from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class OperationalLifecycleTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_agent_instruction_files_are_identical(self) -> None:
        self.assertEqual(self.read("AGENTS.md"), self.read("CLAUDE.md"))
        self.assertIn("Read `MEMORY.md`", self.read("AGENTS.md"))

    def test_shell_entry_points_use_strict_mode_and_parse(self) -> None:
        scripts = [
            "install.sh",
            "setup.sh",
            "build.sh",
            "start.sh",
            "stop.sh",
            "verify.sh",
            "backup.sh",
            "restore.sh",
            "uninstall.sh",
            "purge.sh",
            "scripts/initialize-local-config.sh",
            "scripts/healthcheck.sh",
            "scripts/install_desktop_launcher.sh",
            "scripts/uninstall_desktop_launcher.sh",
            "scripts/launch_ui.sh",
            "scripts/install_prerequisites.sh",
            "scripts/verify_bundle.sh",
            "scripts/import_offline_images.sh",
            "scripts/verify_imported_images.sh",
            "scripts/build_offline_bundle.sh",
            "scripts/build_windows_offline_bundle.sh",
            "scripts/verify_no_egress.sh",
            "scripts/lib/common.sh",
        ]
        for relative in scripts:
            content = self.read(relative)
            self.assertRegex(content, r"set -E?euo pipefail")
            result = subprocess.run(
                ["bash", "-n", str(ROOT / relative)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_setup_is_offline_and_has_non_mutating_preflight(self) -> None:
        setup = self.read("setup.sh")
        self.assertIn("--check", setup)
        self.assertIn("--without-llm", setup)
        self.assertIn("--with-local-model", setup)
        self.assertIn("--no-launcher", setup)
        self.assertIn("Compatibility audit passed", setup)
        self.assertIn("setup will not download", setup)
        self.assertIn('persist_selected_profile', setup)
        self.assertIn('scripts/install_desktop_launcher.sh', setup)
        for prohibited in (
            "docker pull",
            "ollama pull",
            "pip install",
            "apt-get install",
            "brew install",
            "winget",
        ):
            self.assertNotIn(prohibited, setup)

    def test_supported_installer_has_connected_and_offline_modes(self) -> None:
        installer = self.read("install.sh")
        prerequisites = self.read("scripts/install_prerequisites.sh")
        build = self.read("build.sh")
        connected_dockerfile = self.read("backend/Dockerfile.connected")
        requirements = self.read("requirements.runtime.lock")

        for option in (
            "--connected",
            "--offline",
            "--check",
            "--yes",
            "--fresh",
            "--without-llm",
            "--with-local-model",
            "--no-start",
            "--finalize-runtime",
        ):
            self.assertIn(option, installer)
        self.assertIn("install_prerequisites.sh", installer)
        self.assertIn('"$ROOT_DIR/build.sh" --connected', installer)
        self.assertIn("docker pull", build)
        self.assertIn("Dockerfile.connected", build)
        self.assertIn("ollama_command", installer)
        self.assertIn("backup.sh", installer)
        self.assertIn("rollback-", installer)
        self.assertIn("verify.sh", installer)
        self.assertIn("${#prerequisite_args[@]} > 0", installer)
        self.assertIn("${#setup_args[@]} > 0", installer)
        self.assertIn('"$ROOT_DIR/purge.sh" --yes --remove-local-configuration --remove-backups', installer)
        self.assertIn("brew install", prerequisites)
        self.assertIn("apt-get install", prerequisites)
        self.assertIn("preflight.ps1", prerequisites)
        self.assertIn("run_as_root", prerequisites)
        self.assertIn("requirements.runtime.lock", connected_dockerfile)
        self.assertIn("fastapi==", requirements)
        self.assertIn("psycopg-binary==", requirements)

    def test_fresh_install_requires_explicit_approval_before_any_action(self) -> None:
        result = subprocess.run(
            [str(ROOT / "install.sh"), "--fresh", "--without-llm"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Re-run with --yes", result.stderr)

    def test_offline_bundle_is_verified_and_release_evidence_is_generated(self) -> None:
        installer = self.read("install.sh")
        verifier = self.read("scripts/verify_bundle.sh")
        builder = self.read("scripts/build_offline_bundle.sh")

        self.assertIn("verify_bundle.sh", installer)
        self.assertLess(
            installer.index("verify_bundle.sh"),
            installer.index("import_offline_images.sh"),
        )
        self.assertIn("SHA256SUMS.sig", verifier)
        self.assertIn("openssl dgst -sha256 -verify", verifier)
        self.assertIn("docker save", builder)
        self.assertIn("verify_imported_images.sh", installer)
        self.assertIn("RELEASE-MANIFEST.json", builder)
        self.assertIn("python-licenses.tsv", builder)
        self.assertIn("api-image.spdx.json", builder)
        self.assertIn("--signing-key", builder)
        self.assertIn("--source-revision", builder)
        self.assertIn("--archive-format", builder)
        windows_builder = self.read("scripts/build_windows_offline_bundle.sh")
        self.assertIn("--platform linux/amd64", windows_builder)
        self.assertIn("--archive-format zip", windows_builder)
        for prohibited in (".env\" \"$bundle_dir", "certs\" \"$bundle_dir", "backups\" \"$bundle_dir"):
            self.assertNotIn(prohibited, builder)

    def test_unsigned_development_bundle_verifier_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            lines: list[str] = []
            for index in range(10):
                path = bundle / f"artifact-{index}.txt"
                content = f"approved artifact {index}\n"
                path.write_text(content, encoding="utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                lines.append(f"{digest}  ./artifact-{index}.txt\n")
            (bundle / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
            environment = os.environ.copy()
            environment["ALLOW_UNSIGNED_DEVELOPMENT_BUNDLE"] = "true"

            valid = subprocess.run(
                [str(ROOT / "scripts" / "verify_bundle.sh"), str(bundle)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)

            (bundle / "artifact-4.txt").write_text("tampered\n", encoding="utf-8")
            invalid = subprocess.run(
                [str(ROOT / "scripts" / "verify_bundle.sh"), str(bundle)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("Checksum mismatch", invalid.stderr)

    def test_signed_bundle_verifier_accepts_valid_signature(self) -> None:
        if shutil.which("openssl") is None:
            self.skipTest("openssl is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            lines: list[str] = []
            for index in range(10):
                path = bundle / f"signed-artifact-{index}.txt"
                content = f"signed artifact {index}\n"
                path.write_text(content, encoding="utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                lines.append(f"{digest}  ./signed-artifact-{index}.txt\n")
            manifest = bundle / "SHA256SUMS"
            manifest.write_text("".join(lines), encoding="utf-8")
            private_key = bundle / "release-private.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private_key)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(bundle / "RELEASE-PUBLIC-KEY.pem")],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", str(private_key), "-out", str(bundle / "SHA256SUMS.sig"), str(manifest)],
                check=True,
                capture_output=True,
                text=True,
            )
            private_key.unlink()

            result = subprocess.run(
                [str(ROOT / "scripts" / "verify_bundle.sh"), str(bundle)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Release signature verified", result.stdout)

    def test_runtime_verification_checks_health_and_network_isolation(self) -> None:
        verify = self.read("verify.sh")
        egress = self.read("scripts/verify_no_egress.sh")
        compose = self.read("docker-compose.yml")

        self.assertIn("healthcheck.sh", verify)
        self.assertIn("verify_no_egress.sh", verify)
        self.assertIn("running a different image", verify)
        self.assertIn('("1.1.1.1",443)', egress)
        self.assertIn("PostgreSQL has no published host port", egress)
        self.assertIn('com.docker.network.bridge.enable_ip_masquerade: "false"', compose)

    def test_backup_restore_and_uninstall_are_data_preserving(self) -> None:
        backup = self.read("backup.sh")
        restore = self.read("restore.sh")
        uninstall = self.read("uninstall.sh")

        self.assertIn("pg_dump", backup)
        self.assertIn("--format=custom", backup)
        self.assertIn("siligent_sha256", backup)
        self.assertIn("backup.sh", restore)
        self.assertIn("pg_restore", restore)
        self.assertIn("Restore will replace", restore)
        self.assertIn("were preserved", uninstall)
        for prohibited in ("down -v", "volume rm", "system prune"):
            self.assertNotIn(prohibited, uninstall)

    def test_purge_is_explicit_and_scoped_to_scheduler_resources(self) -> None:
        purge = self.read("purge.sh")

        self.assertIn("--yes", purge)
        self.assertIn("--remove-local-configuration", purge)
        self.assertIn("--remove-backups", purge)
        self.assertIn("down --volumes --remove-orphans", purge)
        self.assertIn("product-owned", purge)
        self.assertIn("siligent-scheduler-api", purge)
        self.assertIn("uninstall_desktop_launcher.sh", purge)
        self.assertNotIn("system prune", purge)

    def test_windows_native_entry_points_share_the_checked_lifecycle(self) -> None:
        install = self.read("deploy/windows/install.ps1")
        preflight = self.read("deploy/windows/preflight.ps1")
        common = self.read("deploy/windows/Scheduler.Common.ps1")
        policy = self.read("deploy/windows/network-policy.ps1")

        self.assertIn("Invoke-SchedulerBash", install)
        self.assertIn("Docker.DockerDesktop", preflight)
        self.assertIn("Git.Git", preflight)
        self.assertIn("Ollama.Ollama", preflight)
        self.assertIn("Convert-ToGitBashPath", common)
        self.assertIn("Remove-NetFirewallRule", policy)
        self.assertIn("verify_no_egress.sh", policy)
        shortcut_uninstall = self.read("deploy/windows/uninstall-scheduler-shortcut.ps1")
        self.assertIn("Refusing to remove an unrecognized shortcut", shortcut_uninstall)

    def test_new_install_defaults_to_rules_and_model_checks_are_conditional(self) -> None:
        example = self.read(".env.example")
        compose = self.read("docker-compose.yml")
        config = self.read("backend/config.py")
        setup = self.read("setup.sh")
        self.assertIn("LOCAL_MODEL_ENABLED=false", example)
        self.assertIn("LOCAL_MODEL_ENABLED: ${LOCAL_MODEL_ENABLED:-false}", compose)
        self.assertIn('_boolean("LOCAL_MODEL_ENABLED", False)', config)
        self.assertIn("no Ollama or model artifact required", setup)
        self.assertLess(
            setup.index('"$ROOT_DIR/scripts/initialize-local-config.sh"'),
            setup.index("check_artifact_manifest", setup.index("run_preflight()")),
        )

    def test_offline_artifact_manifest_is_enforced(self) -> None:
        manifest = self.read("deploy/OFFLINE_ARTIFACTS.env")
        setup = self.read("setup.sh")
        build = self.read("build.sh")
        self.assertIn("APPROVED_DATABASE_IMAGE=postgres@sha256:", manifest)
        self.assertIn("APPROVED_API_BASE_REFERENCE=siligent-api@sha256:", manifest)
        self.assertIn("APPROVED_CONNECTED_PYTHON_BASE_REFERENCE=python:", manifest)
        self.assertIn("APPROVED_RUNTIME_REQUIREMENTS_SHA256=", manifest)
        self.assertIn("APPROVED_LOCAL_MODEL_OLLAMA_ID=", manifest)
        self.assertIn("check_image_architecture", setup)
        self.assertIn("APPROVED_LOCAL_MODEL_OLLAMA_ID", setup)
        self.assertIn("APPROVED_API_BASE_REFERENCE", build)

    def test_desktop_launcher_is_health_aware_and_does_not_log_phi(self) -> None:
        launcher = self.read("scripts/launch_ui.sh")
        installer = self.read("scripts/install_desktop_launcher.sh")
        self.assertIn("app_is_healthy", launcher)
        self.assertIn("desktop-launcher.lock", launcher)
        self.assertIn("desktop-launcher.log", launcher)
        self.assertIn('"$ROOT_DIR/start.sh"', launcher)
        self.assertIn('if mkdir "$LOCK_DIR" 2>/dev/null; then', launcher)
        self.assertIn('Treat that as an in-progress launch', launcher)
        self.assertIn("Siligent Scheduler", installer)
        self.assertIn("require_directory_or_absent", installer)
        initializer = self.read("scripts/initialize-local-config.sh")
        self.assertIn("exists but is not a directory", initializer)
        for prohibited in ("patient", "condition_summary", "POSTGRES_PASSWORD"):
            self.assertNotIn(prohibited, launcher)

    def test_daily_start_never_pulls_and_uses_shared_health_check(self) -> None:
        start = self.read("start.sh")
        self.assertIn("--pull never", start)
        self.assertIn("--no-build", start)
        self.assertIn("--prepare-only", start)
        self.assertIn('"$ROOT_DIR/scripts/healthcheck.sh" --wait 60', start)
        self.assertIn("ollama_command", start)

    def test_stop_preserves_database_volume(self) -> None:
        stop = self.read("stop.sh")
        self.assertIn("preserving database volumes", stop)
        self.assertNotIn("down -v", stop)
        self.assertNotIn("volume rm", stop)

    def test_compose_has_service_health_and_isolation(self) -> None:
        compose = self.read("docker-compose.yml")
        self.assertGreaterEqual(compose.count("healthcheck:"), 2)
        self.assertIn("pull_policy: never", compose)
        self.assertIn("internal: true", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("cap_drop:", compose)
        self.assertIn("no-new-privileges:true", compose)

    def test_public_health_response_is_minimal(self) -> None:
        main = self.read("backend/main.py")
        health_block = main.split('@app.get("/health")', 1)[1].split(
            '@app.post("/api/auth/login")', 1
        )[0]
        self.assertIn('"status": "ok"', health_block)
        self.assertIn('"mode": "offline"', health_block)
        self.assertNotIn("local_model_id", health_block)

    def test_calibration_is_optional_and_preserves_approved_policy(self) -> None:
        main = self.read("backend/main.py")
        seed = self.read("backend/seed.py")
        migration = self.read("database/migrations/0011_optional_native_calibration.sql")
        example = self.read(".env.example")

        self.assertIn('CALIBRATION_MIN_SAMPLES=20', example)
        self.assertIn('"data_required_for_scheduling": False', main)
        self.assertIn('"automatic_observations_enabled": True', main)
        self.assertIn("source_batch_id: str | None", main)
        self.assertIn("actual_minutes, outcome,\n                    source", main)
        self.assertIn("does not meet the configured evidence threshold", main)
        self.assertIn("ALTER COLUMN batch_id DROP NOT NULL", migration)
        self.assertIn("ALTER COLUMN source_batch_id DROP NOT NULL", migration)
        unlink_migration = self.read("database/migrations/0012_unlink_native_calibration.sql")
        self.assertIn("DROP COLUMN appointment_id", unlink_migration)
        self.assertIn("source = 'native' AND batch_id IS NULL", unlink_migration)
        self.assertIn("WHERE procedures.policy_version = 'mvp-2026-01'", seed)
        self.assertNotIn("WHERE procedures.policy_version <> 'production-2026-08'", seed)

    def test_reserved_procedure_blocks_have_database_and_confirmation_guards(self) -> None:
        migration = self.read("database/migrations/0013_reserved_procedure_blocks.sql")
        hardening = self.read("database/migrations/0014_reserved_block_guard_hardening.sql")
        consumption = self.read("database/migrations/0015_reserved_block_permission_consumption.sql")
        main = self.read("backend/main.py")
        scheduling = self.read("backend/scheduling.py")

        self.assertIn("reserved_blocks_doctor_no_overlap", migration)
        self.assertIn("reserved_blocks_room_no_overlap", migration)
        self.assertIn("reserved_blocks_equipment_no_overlap", migration)
        self.assertIn("appointments_reserved_block_guard", migration)
        self.assertIn("reserved_block_override_permissions", migration)
        self.assertIn("reserved_block_change_id", migration)
        self.assertIn("history_changed", hardening)
        self.assertIn("p.scheduling_request_id = appointment_row.scheduling_request_id", hardening)
        self.assertIn("AFTER INSERT OR UPDATE", consumption)
        self.assertIn("Reserved-block overrides require an administrator or clinician", main)
        self.assertIn("reserved_block.override_authorized", main)
        self.assertIn("reserved_block.fulfilled", main)
        self.assertIn("allow_reserved_block_override=allow_reserved_block_override", scheduling)

    def test_vacancy_recovery_is_incremental_append_only_and_exact(self) -> None:
        migration = self.read("database/migrations/0016_vacancy_recovery_chains.sql")
        hardening = self.read("database/migrations/0017_vacancy_recovery_guard_hardening.sql")
        main = self.read("backend/main.py")
        recovery = self.read("backend/vacancy_recovery.py")
        scheduling = self.read("backend/scheduling.py")

        self.assertIn("CREATE TABLE vacancy_recovery_chains", migration)
        self.assertIn("CREATE TABLE vacancy_recovery_offers", migration)
        self.assertIn("CREATE TABLE vacancy_recovery_steps", migration)
        self.assertIn("vacancy recovery steps are append-only", migration)
        self.assertIn("released_starts_at > vacancy_starts_at", migration)
        self.assertIn("reschedule_permission_id uuid NOT NULL UNIQUE", migration)
        self.assertIn("requires its exact consumed permission", hardening)
        self.assertIn("offer snapshot is immutable", hardening)
        self.assertIn("chains cannot be deleted", hardening)
        self.assertIn("patient_permission_confirmed", main)
        self.assertIn("exact_move_acknowledged", main)
        self.assertIn('audit_source="vacancy_recovery"', main)
        self.assertNotIn('"medical_record_number": candidate', recovery)
        self.assertIn("DELETE FROM scheduling_requests WHERE id = %s", recovery)
        self.assertIn('"global_schedule_rerun": False', main)
        self.assertIn("a.starts_at > %s", recovery)
        self.assertIn("required_doctor_id", recovery)
        self.assertIn("required_room_id", recovery)
        self.assertIn("required_starts_at", recovery)
        self.assertIn("candidate.interval.start == required_starts_at", scheduling)

    def test_dentist_and_account_lifecycle_preserve_history(self) -> None:
        migration = self.read("database/migrations/0018_doctor_and_account_lifecycle.sql")
        main = self.read("backend/main.py")

        self.assertIn("ADD COLUMN provider_id", migration)
        self.assertIn("enforce_dentist_user_link", migration)
        self.assertIn('"/api/configuration/doctors/{doctor_id}/impact"', main)
        self.assertIn('"/api/configuration/doctors/{doctor_id}/status"', main)
        self.assertIn('"/api/configuration/users/{target_user_id}/status"', main)
        self.assertIn('"/api/configuration/providers/{provider_id}/deletion-impact"', main)
        self.assertIn('"/api/configuration/providers/{provider_id}"', main)
        self.assertIn("permanently_deleted", main)
        self.assertIn("Deactivate the staff member before permanent deletion", main)
        self.assertIn("future appointments remain locked", main)
        self.assertIn("released_block_count", main)
        self.assertIn("doctor.deactivated", main)
        self.assertIn("user.deactivated", main)

    def test_local_configuration_upgrade_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(ROOT / ".env.example", root / ".env.example")
            shutil.copy2(
                ROOT / "scripts" / "initialize-local-config.sh",
                scripts / "initialize-local-config.sh",
            )
            (scripts / "initialize-local-config.sh").chmod(0o755)

            subprocess.run(
                [str(scripts / "initialize-local-config.sh")],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            env_file = root / ".env"
            original = env_file.read_text(encoding="utf-8")
            self.assertNotRegex(original, r"(?m)^[A-Z][A-Z0-9_]*=CHANGE_ME")
            customized = original.replace(
                'PRACTICE_NAME="Siligent Dental"',
                'PRACTICE_NAME="Approved Local Name"',
            )
            env_file.write_text(customized, encoding="utf-8")
            with (root / ".env.example").open("a", encoding="utf-8") as handle:
                handle.write("\nFUTURE_COMPAT_KEY=enabled\n")

            for _ in range(2):
                subprocess.run(
                    [str(scripts / "initialize-local-config.sh")],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            upgraded = env_file.read_text(encoding="utf-8")
            self.assertIn('PRACTICE_NAME="Approved Local Name"', upgraded)
            self.assertEqual(upgraded.count("FUTURE_COMPAT_KEY=enabled"), 1)
            self.assertTrue((root / "certs" / "server.crt").is_file())
            self.assertTrue((root / "certs" / "server.key").is_file())

    def test_local_configuration_explains_a_conflicting_certificate_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(ROOT / ".env.example", root / ".env.example")
            shutil.copy2(
                ROOT / "scripts" / "initialize-local-config.sh",
                scripts / "initialize-local-config.sh",
            )
            (scripts / "initialize-local-config.sh").chmod(0o755)
            (root / "certs").write_text("not a directory", encoding="utf-8")

            result = subprocess.run(
                [str(scripts / "initialize-local-config.sh")],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exists but is not a directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
