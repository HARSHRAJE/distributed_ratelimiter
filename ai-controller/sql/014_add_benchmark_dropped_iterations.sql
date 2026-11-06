ALTER TABLE benchmark_results
    ADD COLUMN dropped_iterations BIGINT
        CHECK (dropped_iterations IS NULL OR dropped_iterations >= 0);
