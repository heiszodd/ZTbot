import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from create_master_models import name_to_tag


def get_valid_tags():
    from engine.rules import RULE_FUNCTIONS

    return {k.removeprefix("rule_") for k in RULE_FUNCTIONS.keys()}


def assign_default_phases(rules: list) -> list:
    """
    If rules have no phase assigned, distribute them:
    First 30% -> Phase 1 (HTF context)
    Next 40%  -> Phase 2 (MTF setup)
    Next 20%  -> Phase 3 (LTF trigger)
    Last 10%  -> Phase 4 (confirmation)
    """
    has_phases = any(r.get("phase") in (1, 2, 3, 4) for r in rules)
    if has_phases:
        return rules

    total = len(rules)
    p1_end = max(1, int(total * 0.30))
    p2_end = max(p1_end + 1, int(total * 0.70))
    p3_end = max(p2_end + 1, int(total * 0.90))

    patched = []
    for i, rule in enumerate(rules):
        r = dict(rule)
        if i < p1_end:
            r["phase"] = 1
        elif i < p2_end:
            r["phase"] = 2
        elif i < p3_end:
            r["phase"] = 3
        else:
            r["phase"] = 4
        patched.append(r)
    return patched


def patch_rules(rules: list, valid_tags: set[str]) -> tuple[list, int, list[str]]:
    rules = assign_default_phases(rules)
    patched = []
    fixed = 0
    missing = []

    for rule in rules:
        r = dict(rule)
        existing_tag = str(r.get("tag", "")).strip().lower()
        if not existing_tag or existing_tag not in valid_tags:
            name = r.get("name", "")
            tag = name_to_tag(name)
            if tag:
                r["tag"] = tag
                fixed += 1
            else:
                missing.append(name)
        patched.append(r)

    return patched, fixed, missing


def patch_all_models():
    db._ensure_pool()
    models = db.get_active_models()
    valid_tags = get_valid_tags()

    print(f"Patching {len(models)} models...")
    total_fixed = 0
    total_missing = []

    for model in models:
        rules = model.get("rules", [])
        if not rules:
            print(f"  {model['name']}: no rules — skip")
            continue

        patched, fixed, missing = patch_rules(rules, valid_tags)
        total_fixed += fixed
        total_missing += missing

        conn = db.acquire_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE models
                    SET rules = %s::jsonb, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (json.dumps(patched), model["id"]),
                )
            conn.commit()
            print(
                f"  {model['name']}: {fixed} rules tagged"
                + (f", {len(missing)} unresolved: {missing}" if missing else "")
            )
        except Exception as exc:
            conn.rollback()
            print(f"  ERROR {model['name']}: {exc}")
        finally:
            db.release_conn(conn)

    print(f"\nDone. {total_fixed} rules tagged total.")
    if total_missing:
        unique_missing = sorted(set(filter(None, total_missing)))
        print(f"{len(unique_missing)} rule names could not be mapped:\n")
        for name in unique_missing:
            print(f"  '{name}'")
        print("\nAdd these to NAME_TO_TAG in create_master_models.py and re-run.")


if __name__ == "__main__":
    patch_all_models()
