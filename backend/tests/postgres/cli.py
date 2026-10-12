"""Operator-only entry point. Plan is offline; other actions require approvals."""
import argparse
import json
import os
from pathlib import Path

from services.platform.test_runtime import activate_test_runtime
from tests.postgres.harness import (apply_048, apply_prerequisites,
    authorize_local_target, capture_migration_plan, sha256)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "provision", "prerequisites", "migration-048", "capture"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    activate_test_runtime()
    if args.action == "plan":
        plan = capture_migration_plan()
        print(json.dumps({"manifest_sha256": sha256(plan.manifest_bytes),
            "files": [path.name for path, _ in plan.sources],
            "migration_048_requires_separate_approval": True}, indent=2))
        return
    if args.action == "provision":
        from tests.postgres.provision import provision_cluster
        from tests.postgres.ownership import exclusive_suite
        with exclusive_suite(authorize_local_target()):
            provision_cluster()
        return
    target = authorize_local_target()
    from tests.postgres.ownership import exclusive_suite
    with exclusive_suite(target):
        if args.action == "prerequisites":
            apply_prerequisites(target)
        elif args.action == "migration-048":
            apply_048(target)
        else:
            if args.output is None:
                parser.error("capture requires --output; metadata is never printed to the console")
            from tests.postgres.schema import capture_local
            snapshot = capture_local(target)
            # Exclusive creation prevents accidentally overwriting an operator export.
            with args.output.open("x", opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
                json.dump(snapshot, output, indent=2)


if __name__ == "__main__":
    main()
