# graphragloader Runbook (Windows)

This runbook documents practical commands, known warnings, and troubleshooting
for large indexing runs (for example `D:\Mainstream` to `D:\mainstreamGraphRAG`).

## 1. Prerequisites

Run from repo root:

```powershell
cd D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent
.\.venv\Scripts\pip.exe install -e ".\graphragloader\.[all]"
```

Additional packages commonly needed in real datasets:

```powershell
.\.venv\Scripts\pip.exe install docx2txt pydub git+https://github.com/openai/whisper.git
```

Install ffmpeg/ffprobe (required by `pydub`):

```powershell
winget install --id Gyan.FFmpeg -e
```

Verify binaries are available:

```powershell
where ffmpeg
where ffprobe
ffmpeg -version
ffprobe -version
```

## 2. Known Good Index Commands

Use `standard` for best extraction quality:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" index `
  --source D:\Mainstream `
  --target D:\mainstreamGraphRAG `
  --include-code `
  --method standard `
  --provider ollama `
  --model gemma4:e4b `
  --embedding-model nomic-embed-text
```

Use `fast` for cheaper/faster first pass:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" index `
  --source D:\Mainstream `
  --target D:\mainstreamGraphRAG `
  --include-code `
  --method fast `
  --provider ollama `
  --model gemma4:e4b `
  --embedding-model nomic-embed-text
```

Notes:
- `standard` = LLM-heavy extraction (better quality, slower).
- `fast` = NLP-oriented extraction (faster, lower quality).
- Do not place `--verbose` at the end. Use `-v` before subcommands, e.g. `graphragloader -v index ...`.

## 3. Two-Step Workflow for Large Files

When files are too large and repeatedly truncated, convert first with a custom cap.

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" convert `
  --source D:\Mainstream `
  --target D:\mainstreamGraphRAG `
  --include-code `
  --max-chars 500000
```

Then index existing input directly:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphrag.exe" index `
  --root D:\mainstreamGraphRAG `
  --method standard
```

## 4. What Warnings Mean

### 4.1 `Please install pydub`
Audio/video support dependency missing. Install `pydub`.

### 4.2 `Please install OpenAI whisper model`
Whisper package missing for speech transcription from media files.

### 4.3 `Couldn't find ffprobe or avprobe`
Python package exists, but system binary is missing from PATH. Install ffmpeg.

### 4.4 `truncated <file> to 200000 chars`
Expected guardrail to control token/runtime costs. Increase `--max-chars` if needed.

### 4.5 `NativeCommandError` in PowerShell
This can appear when stderr output is treated as an exception while command is
still progressing. Check whether indexing actually continues before treating as
fatal.

## 5. Process and Runtime Behavior

- Seeing 1-2 heavy Python processes during indexing is normal.
- Killing those processes is safe, but aborts current run.
- Large corpora can run for hours in `standard` mode.

Check active GraphRAG processes:

```powershell
tasklist | findstr /I graphragloader
tasklist | findstr /I graphrag
```

## 6. Quick Health Checks

Verify converted input exists:

```powershell
(Get-ChildItem D:\mainstreamGraphRAG\input -Filter *.txt).Count
```

Check output artifacts:

```powershell
Get-ChildItem D:\mainstreamGraphRAG\output -Recurse |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 15 Name, LastWriteTime, Length
```

## 7. Minimal Recovery Flow

If run state is unclear:

1. Stop stuck graphrag processes.
2. Re-run `convert` (optionally with `--max-chars`).
3. Re-run `index` using one command (no extra pipe wrappers).
4. Run a simple query after index finishes.

Query example:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" query `
  --target D:\mainstreamGraphRAG `
  --method global `
  --question "Summarize the key components and data flow." `
  --response-type "Detailed Report"
```
