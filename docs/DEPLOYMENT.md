# Deployment & CI/CD

Three levels: **local run**, **simple free cloud deploy**, and **CI/CD**. The
Docker and AWS paths live in [DOCKER.md](DOCKER.md) and
[DEPLOYMENT_AWS.md](DEPLOYMENT_AWS.md).

---

## 1. Local run

```bash
python -m pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
#   set GROQ_API_KEY in .env
python seed/generate_data.py --scale rich
streamlit run src/vantage/app.py
```

---

## 2. Simple cloud deploy — Streamlit Community Cloud (free, no card)

1. Push this repo to GitHub (see §3 for `git init`).
2. Go to <https://share.streamlit.io> → **New app** → pick your repo/branch.
3. **Main file path:** `src/vantage/app.py`.
4. **Advanced settings → Secrets:** add your key in TOML form:
   ```toml
   GROQ_API_KEY = "your_key_here"
   LLM_PROVIDER = "groq"
   ```
5. Deploy.

**Seeding the database in the cloud.** The generated `.db` is git-ignored, so the
cloud app won't have it. Pick one:

- **Commit a small DB** (simplest for a demo):
  ```bash
  python seed/generate_data.py --scale small
  git add -f data/analytics.db && git commit -m "Add demo DB"
  ```
  (`small` ≈ 15 MB — fine for a portfolio demo.)
- **Or generate on first boot** — add to the top of `main()` in `src/vantage/app.py`:
  run `seed/generate_data.py` if the DB file is missing. (Left out by default to
  keep startup predictable.)

> Alternative host: **Hugging Face Spaces** (Streamlit SDK) works the same way —
> set `GROQ_API_KEY` as a Space secret.

---

## 3. CI/CD with GitHub Actions

The pipeline is already defined in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml):

- **On every push/PR:** `ruff` lint + `pytest` (no API key needed).
- **On push:** an **eval gate** that runs the real agent against a subset of the
  golden dataset — but only if a `GROQ_API_KEY` secret exists (otherwise it skips
  cleanly, so forks/PRs never fail). The scorecard is uploaded as an artifact.

**Set it up:**

```bash
git init
git add .
git commit -m "Initial commit: Vantage analytics agent"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Then in GitHub: **Settings → Secrets and variables → Actions → New repository
secret** → add `GROQ_API_KEY`. The eval gate will run on the next push.

**Make it a hard gate (optional).** To fail the build when accuracy drops, have
`eval/run_eval.py` exit non-zero below a threshold — e.g. add at the end of
`main()`:

```python
if scorecard["result_match_rate"] < 0.8:
    raise SystemExit(f"Eval gate failed: result_match_rate={scorecard['result_match_rate']}")
```

**Continuous deploy.** Streamlit Community Cloud and HF Spaces **auto-redeploy on
every push to the tracked branch** — so merging to `main` is your deploy. For the
AWS path, the deploy job (build image → push to ECR → update the service) is in
[DEPLOYMENT_AWS.md](DEPLOYMENT_AWS.md).
