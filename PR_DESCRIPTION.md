# PR Description

## Summary

This change set focuses on architecture hardening and documentation alignment for the LINE webhook backend.

- Queue-based background dispatch is preserved and documented consistently.
- CI now includes a test gate before image build/push.
- Post-deploy verification is integrated as an automated smoke check.
- Documentation is normalized to remove personalized wording and stale behavior notes.

## Scope

### Architecture
- Keep signature verification as the first gate in webhook ingress.
- Keep bounded queue + hosted worker for async processing.
- Keep dispatcher-based routing for text/image/file/postback.

### Reliability and Operations
- Ensure `dotnet test` blocks deployment on failure.
- Verify deployment health with:
  - `GET /health` returns `200`
  - invalid signature to `POST /api/line/webhook` returns `401`

### Documentation
- Normalize style by document type:
  - Product docs: concise, user-facing, present tense
  - Deployment docs: checklist-driven, operational language
  - Planning docs: roadmap-oriented, explicit assumptions
  - Review/assessment docs: point-in-time snapshot language
- Remove personalized identity references.
- Remove stale statements that conflict with current implementation.

## Behavior Notes

- Group/room text handling remains mention-gated.
- Group image handling remains ignored by default flow.
- Group file handling is configurable via `App:AllowGroupFileHandling`.
- File support includes `.txt/.md/.csv/.json/.xml/.log/.pdf/.docx/.xlsx/.pptx`.

## Validation

- All tests pass in the current solution.
- Deployment workflow executes successfully after syntax fixes.
- Repository remains clean after commit and push.

## Risk

Low-to-medium.

- Runtime behavior change is limited.
- Main risk is documentation drift, mitigated by this normalization update.
