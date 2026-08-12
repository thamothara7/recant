import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from fanout.consumer_entry import _tenant_role_name, _tenant_roles_enabled


def test_lambda_modules_import_from_fanout_only_package(tmp_path):
    package = tmp_path / "fanout"
    package.mkdir()
    source = Path(__file__).parents[2] / "fanout"
    for name in ("__init__.py", "handler.py", "lambda_entry.py", "consumer_entry.py"):
        shutil.copy2(source / name, package / name)

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(tmp_path)!r}); "
                "import fanout.lambda_entry, fanout.consumer_entry"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_packaged_consumer_production_cannot_disable_tenant_role(monkeypatch):
    monkeypatch.setenv("RECANT_ENV", "production")
    monkeypatch.setenv("RECANT_DB_RLS", "false")

    assert _tenant_roles_enabled() is True
    assert _tenant_role_name(UUID("12345678-1234-5678-1234-567812345678")) == (
        "recant_t_12345678123456781234567812345678"
    )
