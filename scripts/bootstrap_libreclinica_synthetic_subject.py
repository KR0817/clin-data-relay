"""Create the approved synthetic subject/event fixture through LibreClinica SOAP."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta

from app.edc_adapter import EdcAdapterError, LibreClinicaSoapAdapter, load_edc_adapter_from_environment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", default="SUBJ001")
    parser.add_argument("--event", default="WEEK_0")
    parser.add_argument("--date", default=(date.today() - timedelta(days=1)).isoformat())
    args = parser.parse_args()
    os.environ.setdefault("COMPANION_EDC_MODE", "libreclinica_soap")
    adapter = load_edc_adapter_from_environment()
    if not isinstance(adapter, LibreClinicaSoapAdapter):
        print(json.dumps({"status": "blocked", "readiness": adapter.readiness()}, ensure_ascii=False))
        return 1
    readiness = adapter.readiness()
    if readiness["status"] != "ready":
        print(json.dumps({"status": "blocked", "readiness": readiness}, ensure_ascii=False))
        return 1
    fixture_date = date.fromisoformat(args.date)
    actions: list[str] = []
    try:
        adapter.resolve_subject_oid(args.subject)
    except EdcAdapterError as error:
        if error.code != "libreclinica_subject_not_found":
            raise
        adapter.create_synthetic_subject(args.subject, fixture_date)
        actions.append("subject_created")
    if not adapter.has_scheduled_event(args.subject, args.event):
        adapter.schedule_synthetic_event(args.subject, args.event, fixture_date)
        actions.append("event_scheduled")
    print(
        json.dumps(
            {
                "status": "ready",
                "subject": args.subject,
                "event": args.event,
                "actions": actions or ["already_ready"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
