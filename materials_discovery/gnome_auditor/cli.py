"""CLI entry points for the GNoME Auditor.

Subcommands: ingest, validate, cross-ref, chat, stats
"""

import argparse
import sys


def cmd_ingest(args):
    """Run data ingestion: filter CSV → extract CIFs → populate DB."""
    from gnome_auditor.data.ingest import run_ingestion
    count = run_ingestion()
    print(f"\nIngestion complete: {count} materials in database.")


def cmd_validate(args):
    """Run validation pipeline on all materials."""
    from gnome_auditor.pipeline import run_full_pipeline, validate_material
    if args.material_id:
        from gnome_auditor.db.store import get_connection
        conn = get_connection()
        result = validate_material(args.material_id, conn=conn, force=args.force)
        conn.close()
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Validated {args.material_id}:")
            oxi = result["oxi_assignment"]
            print(f"  Oxidation states: {oxi.get('oxi_states')} (confidence: {oxi.get('confidence')})")
            for r in result["results"]:
                print(f"  {r.check_name}: status={r.status}, passed={r.passed}, score={r.score}")
    else:
        run_full_pipeline(force=args.force)


def cmd_crossref(args):
    """Run Materials Project cross-referencing."""
    from gnome_auditor.data.mp_cross_ref import run_mp_cross_reference
    run_mp_cross_reference(api_key=args.api_key)


def cmd_chat(args):
    """Start the Claude research assistant chat."""
    from gnome_auditor.claude_interface import run_chat
    run_chat()


def cmd_stats(args):
    """Print database statistics."""
    from gnome_auditor.db.store import get_connection, get_statistics, get_audit_summary

    conn = get_connection()
    stats = get_statistics(conn)
    summary = get_audit_summary(conn)
    conn.close()

    print(f"\n{'='*60}")
    print(f"GNoME Auditor Database Statistics")
    print(f"{'='*60}")
    print(f"Total materials: {stats['total_materials']}")

    if stats["oxidation_state_confidence"]:
        print(f"\nOxidation State Confidence:")
        for conf, cnt in sorted(stats["oxidation_state_confidence"].items()):
            print(f"  {conf}: {cnt}")

    if summary:
        print(f"\nValidation Summary:")
        print(f"  {'Check':<25} {'Computed':>8} {'Passed':>8} {'Failed':>8} {'Skipped':>8} {'Errors':>8}")
        print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
        for row in summary:
            print(f"  {row['check_name']:<25} {row['computed']:>8} {row['passed']:>8} "
                  f"{row['failed']:>8} {row['skipped_no_params']:>8} {row['errors']:>8}")

    if stats["mp_match_types"]:
        print(f"\nMP Match Types:")
        for mt, cnt in sorted(stats["mp_match_types"].items()):
            print(f"  {mt}: {cnt}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="GNoME Auditor — Chemistry-based validation of GNoME predictions",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ingest
    sub = subparsers.add_parser("ingest", help="Ingest GNoME ternary oxide data")
    sub.set_defaults(func=cmd_ingest)

    # validate
    sub = subparsers.add_parser("validate", help="Run validation pipeline")
    sub.add_argument("--material-id", "-m", help="Validate a single material by ID")
    sub.add_argument("--force", "-f", action="store_true", help="Recompute existing results")
    sub.set_defaults(func=cmd_validate)

    # cross-ref
    sub = subparsers.add_parser("cross-ref", help="Run Materials Project cross-referencing")
    sub.add_argument("--api-key", help="MP API key (or set MP_API_KEY env var)")
    sub.set_defaults(func=cmd_crossref)

    # chat
    sub = subparsers.add_parser("chat", help="Start Claude research assistant")
    sub.set_defaults(func=cmd_chat)

    # stats
    sub = subparsers.add_parser("stats", help="Print database statistics")
    sub.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
