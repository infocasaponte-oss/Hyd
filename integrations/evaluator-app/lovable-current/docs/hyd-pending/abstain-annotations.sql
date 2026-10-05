-- PENDENTE (non aplicada): táboa aparte para marcar cada abstain como perigosa ou por falta de contexto.
-- Aditiva: non toca hyd_records. Cada avaliador só anota e ve os seus propios abstain.
CREATE TABLE public.hyd_abstain_annotations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  record_id uuid NOT NULL UNIQUE REFERENCES public.hyd_records(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('dangerous','missing_context')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.hyd_abstain_annotations TO authenticated;
GRANT ALL ON public.hyd_abstain_annotations TO service_role;
ALTER TABLE public.hyd_abstain_annotations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Own annotations select" ON public.hyd_abstain_annotations FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Own annotations insert" ON public.hyd_abstain_annotations FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = user_id AND EXISTS (SELECT 1 FROM public.hyd_records r WHERE r.id = record_id AND r.user_id = auth.uid() AND r.expected_label = 'abstain'));
CREATE POLICY "Own annotations update" ON public.hyd_abstain_annotations FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Own annotations delete" ON public.hyd_abstain_annotations FOR DELETE TO authenticated USING (auth.uid() = user_id);
