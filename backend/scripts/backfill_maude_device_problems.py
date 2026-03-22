import json
import logging
import os
import sys


sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from crawlers.fda_maude import FDAMaudeCrawler
from database import get_db


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill-maude-device-problems")


def main():
    crawler = FDAMaudeCrawler()
    conn = get_db()
    updated = 0
    skipped = 0
    failed = 0

    try:
        rows = conn.execute(
            "SELECT id, raw_data, device_problem FROM adverse_events ORDER BY id ASC"
        ).fetchall()

        logger.info("開始回填 adverse_events.device_problem，共 %s 筆", len(rows))

        for row in rows:
            event_id = row["id"]
            raw_data = row["raw_data"]

            if not raw_data:
                skipped += 1
                continue

            try:
                item = json.loads(raw_data)
                devices = item.get("device", [{}])
                device = devices[0] if isinstance(devices, list) and devices else {}
                device_problem = crawler._extract_device_problem(item, device)

                if device_problem == (row["device_problem"] or ""):
                    skipped += 1
                    continue

                conn.execute(
                    "UPDATE adverse_events SET device_problem = ? WHERE id = ?",
                    (device_problem, event_id),
                )
                updated += 1
            except Exception as exc:
                failed += 1
                logger.warning("事件 %s 回填失敗: %s", event_id, exc)

        conn.commit()
        logger.info(
            "回填完成: updated=%s skipped=%s failed=%s",
            updated,
            skipped,
            failed,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
