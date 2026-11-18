ALTER TABLE failures ADD COLUMN classification_key TEXT;
ALTER TABLE failures ADD COLUMN category TEXT;
ALTER TABLE failures ADD COLUMN severity TEXT;
CREATE UNIQUE INDEX idx_failures_classification_key ON failures (classification_key);
