"""Phase 9 analytics: Meta insights collection, normalization, storage,
calculations, synchronization, queries and reports.

Layers (each module depends only on the ones above it):

1. ``metrics``      - the catalogue of supported, officially documented metrics.
2. ``errors``       - classification of Meta API failures for collection.
3. ``collector``    - Meta Graph API data collection (pagination, chunking).
4. ``storage``      - normalized snapshot / post upserts (no duplicates).
5. ``calculations`` - documented derived metrics (rates, changes).
6. ``sync``         - background synchronization jobs and retries.
7. ``queries``      - aggregations for the analytics API.
8. ``reports``      - CSV and PDF exports.
9. ``summaries``    - optional Groq natural-language interpretation.
"""
