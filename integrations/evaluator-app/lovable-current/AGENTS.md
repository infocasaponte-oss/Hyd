<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

# Project rules

- Hyd evaluator records live in the `hyd_records` table; every record requires consent (CHECK `consent = true`) and stores the exact consent text per row.
- Evaluator questions are stored verbatim — never rewrite, translate, or paraphrase them anywhere in the pipeline.
- The AI second opinion (AI Gateway) is only requested AFTER the evaluator has chosen the expected label; it is stored in separate `ai_*` fields and never overwrites an existing opinion.
- JSONL export follows Hyd's training format (`text`/`expected`) with a `meta` block (`real: true, synthetic: false, consent, author, created_at, ai_second_opinion`).
- Hyd model work (training, calibration, changelog) lives outside this app in /tmp/hyd; every change is logged there as docs/CHANGELOG-HYD.md entries (HYD-XXX).
