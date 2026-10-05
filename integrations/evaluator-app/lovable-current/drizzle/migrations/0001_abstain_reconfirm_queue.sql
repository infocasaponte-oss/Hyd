CREATE TABLE public.hyd_abstain_reconfirm_queue (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  annotation_id uuid NOT NULL UNIQUE,
  record_id uuid NOT NULL REFERENCES public.hyd_records(id) ON DELETE CASCADE,
  owner_id uuid NOT NULL,
  ai_kind text NOT NULL CHECK (ai_kind IN ('dangerous','missing_context')),
  reason text NOT NULL DEFAULT 'HYD-023: marca cambiada por asistente IA; valor humano orixinal non conservado',
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','reviewed')),
  confirmed_kind text CHECK (confirmed_kind IN ('dangerous','missing_context','unsure')),
  confirmed_by uuid,
  confirmed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'pending' AND confirmed_kind IS NULL) OR (status = 'reviewed' AND confirmed_kind IS NOT NULL AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL))
);
GRANT SELECT ON public.hyd_abstain_reconfirm_queue TO authenticated;
GRANT UPDATE (status, confirmed_kind, confirmed_by, confirmed_at) ON public.hyd_abstain_reconfirm_queue TO authenticated;
GRANT ALL ON public.hyd_abstain_reconfirm_queue TO service_role;
ALTER TABLE public.hyd_abstain_reconfirm_queue ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Owner reads own queue" ON public.hyd_abstain_reconfirm_queue FOR SELECT TO authenticated USING (auth.uid() = owner_id);
CREATE POLICY "Owner confirms own queue" ON public.hyd_abstain_reconfirm_queue FOR UPDATE TO authenticated
  USING (auth.uid() = owner_id) WITH CHECK (auth.uid() = owner_id AND confirmed_by = auth.uid());
COMMENT ON TABLE public.hyd_abstain_reconfirm_queue IS 'Cola de reconfirmación humana das marcas abstain cambiadas pola IA (HYD-023). Non modifica hyd_abstain_annotations nin hyd_records. Ata status=reviewed, a marca é só diagnóstico.';