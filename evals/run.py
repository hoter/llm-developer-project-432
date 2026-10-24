"""Прогон метрик на эталонном наборе документов.

По умолчанию — подмножество из golden_cards.json (eval_defaults): локальная
модель медленная. Весь набор: ``make eval ALL=1``.

Отчёт сохраняется файлом в evals/reports/, иначе сравнить «до» и «после»
правки промпта не с чем.
"""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core import db
from app.core.logging import setup_logging
from app.repositories import documents as documents_repo
from app.services.rag_pipeline import run_pipeline
from evals.judge import judge_card
from evals.metrics import characteristic_match, citation_support

GOLDEN = Path("data/golden_cards.json")
REPORTS = Path("evals/reports")


async def evaluate(use_all: bool) -> dict:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    documents = golden["documents"]
    selected = list(documents) if use_all else list(golden["eval_defaults"])

    with db.connection() as conn:
        indexed = {row["filename"]: row for row in documents_repo.get_documents_meta(conn)}

    rows = []
    for filename in selected:
        expected = documents[filename]
        document = indexed.get(filename)
        if not document or document["status"] != "indexed":
            rows.append(
                {
                    "document": filename,
                    "skipped": "документ не найден в базе или не проиндексирован",
                }
            )
            continue

        result = await run_pipeline([document["id"]], hint=expected.get("product"))
        characteristics = characteristic_match(
            expected.get("characteristics", {}), result.draft.characteristics
        )
        citations = citation_support(
            result.draft, result.context, expected.get("source_probes", {})
        )
        verdict = await judge_card(result.draft, result.context)

        rows.append(
            {
                "document": filename,
                "characteristic_match": round(characteristics["score"], 3),
                "missing_characteristics": characteristics["missed"],
                "citation_support": round(citations["score"], 3),
                "citation_failed": citations["failed"],
                "judge_supported": verdict.supported,
                "judge_unsupported_claims": verdict.unsupported_claims,
                "attempts": result.attempts,
                "verdict": result.verdict,
                "confidence": result.draft.confidence,
                "missing_fields": result.draft.missing_fields,
            }
        )
        print(
            f"  {filename:24} chars={characteristics['score']:.2f} "
            f"citations={citations['score']:.2f} judge={verdict.supported}"
        )

    scored = [row for row in rows if "skipped" not in row]
    averages = {}
    if scored:
        averages = {
            "characteristic_match": round(
                sum(row["characteristic_match"] for row in scored) / len(scored), 3
            ),
            "citation_support": round(
                sum(row["citation_support"] for row in scored) / len(scored), 3
            ),
            "judge_supported": round(
                sum(1 for row in scored if row["judge_supported"]) / len(scored), 3
            ),
        }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "golden": str(GOLDEN),
        "subset": not use_all,
        "documents": rows,
        "averages": averages,
    }
    return report


def print_table(report: dict) -> None:
    header = f"{'документ':26} {'chars':>6} {'cites':>6} {'judge':>6} {'verdict':>18}"
    print()
    print(header)
    print("-" * len(header))
    for row in report["documents"]:
        if "skipped" in row:
            print(f"{row['document']:26}   —    {row['skipped']}")
            continue
        print(
            f"{row['document']:26} {row['characteristic_match']:6.2f} "
            f"{row['citation_support']:6.2f} "
            f"{'ok' if row['judge_supported'] else 'no':>6} {row['verdict']:>18}"
        )
    averages = report["averages"]
    if averages:
        print("-" * len(header))
        print(
            f"{'средние':26} {averages['characteristic_match']:6.2f} "
            f"{averages['citation_support']:6.2f} {averages['judge_supported']:6.2f}"
        )


def save_report(report: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = REPORTS / f"eval-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def amain(use_all: bool) -> None:
    setup_logging()
    print(f"Метрики: {'весь набор' if use_all else 'подмножество'} ({GOLDEN})")
    report = await evaluate(use_all)
    print_table(report)
    path = save_report(report)
    print(f"\nотчёт сохранён: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Метрики качества генерации")
    parser.add_argument(
        "--all", action="store_true", help="прогнать весь набор, а не подмножество"
    )
    args = parser.parse_args()
    asyncio.run(amain(args.all))


if __name__ == "__main__":
    main()
