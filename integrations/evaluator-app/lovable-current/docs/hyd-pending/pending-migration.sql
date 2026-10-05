-- NOT APPLIED. Additive only. Keeps existing owner RLS policies and CHECK (consent = true).
ALTER TABLE public.hyd_records
  ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'unknown'
    CHECK (source_kind IN ('user_traffic','human_evaluator','ai_assisted','synthetic','unknown')),
  ADD COLUMN IF NOT EXISTS consent_version text NOT NULL DEFAULT 'legacy-unversioned',
  ADD COLUMN IF NOT EXISTS rights_declared boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS rights_verified boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS rights_license text,
  ADD COLUMN IF NOT EXISTS external_ai_consent boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS ai_prompt_sha256 text,
  ADD COLUMN IF NOT EXISTS ai_input_sha256 text,
  ADD COLUMN IF NOT EXISTS ai_created_at timestamptz,
  ADD COLUMN IF NOT EXISTS ai_authority boolean NOT NULL DEFAULT false CHECK (ai_authority = false);

CREATE OR REPLACE FUNCTION public.hyd_records_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.consent_version = 'legacy-unversioned' THEN RAISE EXCEPTION 'Explicit consent version required'; END IF;
    IF NEW.rights_verified THEN RAISE EXCEPTION 'rights_verified only via offline verification'; END IF;
    RETURN NEW;
  END IF;
  IF NEW.question IS DISTINCT FROM OLD.question OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.consent IS DISTINCT FROM OLD.consent OR NEW.consent_text IS DISTINCT FROM OLD.consent_text
     OR NEW.consent_version IS DISTINCT FROM OLD.consent_version OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Question, owner, consent and date are immutable; add a correction instead';
  END IF;
  IF OLD.source_kind <> 'unknown' AND NEW.source_kind IS DISTINCT FROM OLD.source_kind THEN
    RAISE EXCEPTION 'Declared provenance is immutable';
  END IF;
  IF OLD.ai_label IS NOT NULL AND (NEW.ai_label, NEW.ai_intent, NEW.ai_confidence, NEW.ai_model)
     IS DISTINCT FROM (OLD.ai_label, OLD.ai_intent, OLD.ai_confidence, OLD.ai_model) THEN
    RAISE EXCEPTION 'Existing AI opinion is never overwritten';
  END IF;
  IF NEW.rights_verified IS DISTINCT FROM OLD.rights_verified THEN
    RAISE EXCEPTION 'rights_verified only via offline verification';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER hyd_records_guard_trg BEFORE INSERT OR UPDATE ON public.hyd_records
  FOR EACH ROW EXECUTE FUNCTION public.hyd_records_guard();

CREATE TABLE public.hyd_question_corrections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  record_id uuid NOT NULL REFERENCES public.hyd_records(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL,
  original_text text NOT NULL,
  corrected_text text NOT NULL,
  reason text NOT NULL,
  human_accepted boolean NOT NULL CHECK (human_accepted = true),
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON public.hyd_question_corrections TO authenticated;
GRANT ALL ON public.hyd_question_corrections TO service_role;
ALTER TABLE public.hyd_question_corrections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Evaluators view own corrections" ON public.hyd_question_corrections
  FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Evaluators add corrections to own records" ON public.hyd_question_corrections
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id AND EXISTS (
    SELECT 1 FROM public.hyd_records r WHERE r.id = record_id AND r.user_id = auth.uid() AND r.question = original_text));
