# Launches Vantage with the correct interpreter (system Python 3.11),
# regardless of whether a conda environment is active in your shell.
#
# Usage:  .\run.ps1      (from a PowerShell prompt in this folder)
# If blocked by execution policy, run once:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".env")) {
    Write-Host "!! No .env found. Copy .env.example to .env and set GROQ_API_KEY first." -ForegroundColor Yellow
}

if (-not (Test-Path "data\analytics.db")) {
    Write-Host ">> No database found - generating the 'rich' dataset (one time)..." -ForegroundColor Cyan
    py -3.11 "seed\generate_data.py" --scale rich
}

Write-Host ">> Starting Streamlit on http://localhost:8501" -ForegroundColor Green
py -3.11 -m streamlit run "src\vantage\app.py"
