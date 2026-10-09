# Market Radar — daily research version

Open Market radar after unlocking the dashboard. Fetch at least 21 daily sessions in Market data first. GET /radar requires the same operator authentication as other private routes. It reads local data only and cannot place orders. The browser reloads the snapshot every 60 seconds; this does not fetch fresh exchange prices.

Score = (latest close - latest open) / mean(high - low) over the preceding 20 sessions. The latest candle is excluded from that baseline. If the larger open-to-extreme range is not greater than twice the opposite range, the score is zero. Rank is descending absolute strength, with symbol tie breaking. These transparent research rules are our implementation, not a reproduction of a proprietary vendor algorithm.

Breadth compares close to previous close, independent of strength. Only instruments sharing the newest loaded session enter the board, breadth and equal-weight sector averages. Older histories are explicitly excluded. The bundled small sector taxonomy is illustrative and does not establish current F&O eligibility. Unmatched stocks remain Unclassified. Prior 20-session high/low lines are historical levels, not institutional order blocks.

The existing Parquet store discards provider provenance and can contain mock candles. Therefore every snapshot is labelled stored_daily / unverified, even when originally imported from a broker. No live claim, win probability, institutional flow inference, exchange-wide breadth or complete F&O coverage is made. Today's stored candle may be incomplete. Invalid histories, duplicate daily sessions, future sessions and unreadable files are excluded. Scan is capped at 300 directories with a visible truncation indicator.

Before live rollout: isolate source-labelled datasets, establish licensed quote ingestion and exchange instrument/sector masters, apply exchange holiday/session rules and corporate-action adjustments, and validate timestamp freshness. This release deliberately exposes the existing daily dataset honestly.

Validation: python -m unittest scripts.test_radar; npm --prefix apps/dashboard run build.
