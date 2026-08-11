-- Phase 4: GeoLite2 enrichment columns.
ALTER TABLE attendance_records
  ADD COLUMN city VARCHAR(100) NULL AFTER isp,
  ADD COLUMN region VARCHAR(100) NULL AFTER city,
  ADD COLUMN country VARCHAR(60) NULL AFTER region;
