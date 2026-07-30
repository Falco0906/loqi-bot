-- M2.8.2 — User Activation Foundation
-- Adds onboarding wizard data fields to users table

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'onboarding_data'
    ) THEN
        ALTER TABLE users ADD COLUMN onboarding_data TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'onboarding_completed_at'
    ) THEN
        ALTER TABLE users ADD COLUMN onboarding_completed_at TIMESTAMPTZ;
    END IF;
END $$;