# StudyLens

A private learning workspace built with Django REST Framework, Next.js/TypeScript,
PostgreSQL, Celery/Redis, Tesseract and Ollama. The application persists real data;
there are no simulated AI answers or fabricated progress metrics.

Start with **[verification and limitations](docs/verification.md)** for the exact
delivery status. This is a substantial university-project implementation, not a
claim that every production concern in the supplied specification is complete.

Locally verified: **33 backend tests + 3 frontend tests + 2 Chrome browser tests**,
TypeScript, Django checks/migrations and the production frontend build. One real OCR
test was skipped because this host does not have Tesseract.

## Windows: open StudyLens with its background services

Install Docker Desktop with Linux containers, then double-click **Start-StudyLens.cmd**
in the extracted project folder. It creates `.env` only if missing, starts Docker Desktop
when needed, builds/starts the complete stack, checks Redis and Celery, and opens
[StudyLens](http://localhost:8080). You do not need separate Redis/Celery terminals.
The first start needs internet for container images and dependencies and can take several minutes.
Subsequent starts reuse the containers and persistent volumes.

Use this launcher each time you open the app; opening an ordinary browser bookmark
cannot start stopped services. Services restart when Docker starts unless explicitly
stopped. Enable Docker Desktop's sign-in startup setting if you want Docker available
automatically after signing into Windows. To stop StudyLens, run `docker compose stop`;
the launcher starts it again. Do not use `docker compose down -v` unless deleting data.

This launcher uses the Docker database and media volumes. A prior native development
SQLite database and uploads are separate and are not automatically migrated into Docker.
For tutor and quiz generation, download the Ollama model once using the command below.

## Downloading material

**Download original** returns the uploaded PDF or image with its correct file extension
and media type, even for files uploaded before this fix. Processing does not turn the
original image into a text file. For the processed OCR/native PDF text, use **Download
extracted text (.txt)** after processing. It exports the currently saved page text and
review corrections in page order as Unicode text; save edits before downloading.

## Quick start — Docker Compose

Requires Docker with Compose v2.24+ and enough disk/RAM for the model and services.
Run these commands from this `studylens` directory:

```sh
cp .env.example .env
docker compose up --build -d
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec backend python manage.py createsuperuser
```

PowerShell: use `Copy-Item .env.example .env` for the first command.
Open [StudyLens](http://localhost:8080), register, and create your first course.
Django administration is at [admin](http://localhost:8080/admin/).
Migrations and static collection run through the one-shot `migrate` service.
The model download is necessary for tutor, syllabus, timetable and quiz generation.
Native PDF extraction, scheduling, manual entry and exports work without the model.
OCR is installed in the backend/worker container. Ollama and database ports are private.

If the queue is unavailable, the application marks the job failed with an actionable
message. Start the worker/Redis and retry. Run only one beat scheduler instance.

## Local development without Docker

Python 3.12 and Node.js 22.18+ (or 24) are supported. SQLite is an explicit local/test
fallback; production settings require PostgreSQL. Set environment variables in your
shell; the Python process does not automatically read `.env` files.

```sh
cd backend
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open [localhost:3000](http://localhost:3000). Next.js proxies `/api` to Django,
so authentication and CSRF stay same-origin. Set `BACKEND_URL` before building
if Django uses another address.

For background jobs, run Redis and `celery -A config worker --loglevel=info` plus
`celery -A config beat --loglevel=info` from the backend directory. Celery's supported
deployment is Linux/containers. For a Windows-only demonstration, set
`CELERY_TASK_ALWAYS_EAGER=1` before launching Django; jobs execute synchronously
and block requests. This is a development fallback, not a production configuration.
Install Tesseract separately and ensure `tesseract` is on PATH. Run Ollama locally
and pull the configured model. Failure to install these services is shown as an
error; it is never replaced with a pretend result.

## First complete workflow

1. Register and save profile timezone, study preferences and weekly availability.
2. Create a course and upload the sample notes from `backend/tests/fixtures/`.
3. Open the document, click **Process / reprocess material**, review pages and
   **Confirm reviewed extraction**. Correcting a page invalidates its confirmation.
4. Upload and review the sample syllabus; click **Extract syllabus** with Ollama
   running, or manually add topics inside the course. Review suggested mappings.
5. Open **AI study partner**, start a conversation and ask about normalization.
   Open the exact page/quote citations to inspect the evidence.
6. Generate a quiz. The worker validates shape, choices, topic IDs and source quotes;
   submit once for server-side scoring. Review explanations and mastery evidence.
7. Upload/review a timetable or manually enter an exam. Confirm its date explicitly.
8. Generate a draft plan, inspect unscheduled work/conflicts, then accept it.
9. Start, skip or complete sessions and record actual minutes. Review proposed plan
   versions; only **Apply Updated Plan** replaces the accepted plan.
10. Export your plan to PDF/ICS or download a background-generated personal-data bundle.

The sample documents are development fixtures and are never inserted into accounts.

## Validation commands

```sh
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
ruff check .
python manage.py spectacular --file ../docs/api/openapi.yaml
cd ../frontend
npm run typecheck
npm test -- --configLoader native
npm run build
cd ../e2e
npm ci
npx playwright install chromium
npm test
```

The browser test starts Django and Next automatically; migrate the database first.
The optional real OCR test skips when Tesseract is absent. AI unit tests use explicit
test doubles to validate contracts; they do not demonstrate real model quality.
CI workflows are supplied for backend, frontend and browser tests.

## Architecture and project layout

- [Architecture and acceptance criteria](docs/architecture/overview.md)
- [Data flow and deletion](docs/architecture/data-flow.md)
- [AI pipeline and hardware](docs/architecture/ai-pipeline.md)
- [Scheduling rules](docs/architecture/scheduling.md)
- [API conventions](docs/api/conventions.md) and generated [OpenAPI](docs/api/openapi.yaml)
- [Deployment](docs/runbooks/deployment.md), [backup/restore](docs/runbooks/backup-restore.md),
  [incident response](docs/runbooks/incident-response.md)
- [Actual file inventory](docs/file-tree.txt)

Domain models follow the supplied backend boundaries. HTTP resources are consolidated
in `backend/common/views.py`; service modules hold domain logic. Frontend workflow
screens are consolidated in `src/features/workspace/Workspace.tsx`, with App Router
paths and shared API/types. This avoids empty scaffolding but is less granular than
the proposed feature-by-feature component tree. npm's committed lockfile is canonical;
Poetry and pnpm lockfiles are intentionally not fabricated. Python runtime versions
are resolved in `backend/requirements.lock`; Docker and development test installation
use that lock. `requirements.txt` records the supported version ranges.

## Local AI resources

Plan for roughly 16 GB system RAM and 10–20 GB free disk beyond uploaded data and
backups. The configured 3B model is a multi-gigabyte download. A supported GPU can
reduce latency, but CPU-only generation is possible and may take minutes. These are
planning estimates, not measured benchmarks. More detail is in `infra/ollama/README.md`.
Tesseract uses English OCR by default; explanation language is a separate preference.
Fonts have system fallbacks if Google Fonts is unavailable.

## Data retention

Private uploads have no public media route. Authenticated downloads enforce ownership.
Delete cascades remove live records and indexes/mappings; file removal is registered
after transaction commit. Deleting a source document conservatively removes its
course's chats/quizzes/mastery so copied excerpts cannot survive in derived content.
Full exports are invalidated on source deletion and expire after 24 hours. Externally
downloaded copies cannot be recalled. Operators must enforce the documented backup
retention/deletion procedure before treating this as a public production service.
